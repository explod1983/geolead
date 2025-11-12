from __future__ import annotations

# =============================================================================
# GeoGuessr Leaderboard — Minimal FastAPI app with Jinja2 templates and sessions
# - Registration/Login via signed cookie sessions (email + name)
# - Submit 3-round scores (total + timestamp calculated automatically)
# - Leaderboards for All time / This week / Today
# - Enforce one submission per user per UTC day
# - Shows best single-round ("max round") per player
# =============================================================================

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Literal, List

from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field

from sqlalchemy import (
    create_engine,
    Integer,
    String,
    DateTime,
    ForeignKey,
    select,
    func,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
    Session,
)
from sqlalchemy.exc import IntegrityError

# ---------- Paths & DB ---------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_URL = f"sqlite:///{ROOT.parent / 'geoguessr.db'}"
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Base for SQLAlchemy ORM models."""
    pass


class Player(Base):
    """Registered player (email+name)."""
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)   # non-unique in model (legacy DBs may still have UNIQUE)
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    entries: Mapped[List["ScoreEntry"]] = relationship(back_populates="player")


class ScoreEntry(Base):
    """One submitted game with 3 rounds and computed total."""
    __tablename__ = "score_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    round1: Mapped[int] = mapped_column(Integer)
    round2: Mapped[int] = mapped_column(Integer)
    round3: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[int] = mapped_column(Integer)

    player: Mapped[Player] = relationship(back_populates="entries")


# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

# Lightweight migration: ensure 'email' column exists; add helpful index
with engine.connect() as conn:
    cols = [row[1] for row in conn.execute(text("PRAGMA table_info(players)"))]
    if "email" not in cols:
        conn.execute(text("ALTER TABLE players ADD COLUMN email VARCHAR(255)"))
        conn.commit()
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_players_email ON players(email)"))
    conn.commit()

# ---------- FastAPI app & Jinja -----------------------------------------------
app = FastAPI(title="GeoGuessr Leaderboard", version="0.4.5")

# Demo secret for sessions; replace with env var for production
app.add_middleware(SessionMiddleware, secret_key="change-me-please-very-secret")

static_dir = ROOT / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- JSON Schemas (optional API) ---------------------------------------
class SubmitEntryIn(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=80)
    round1: int = Field(..., ge=0, le=5000)
    round2: int = Field(..., ge=0, le=5000)
    round3: int = Field(..., ge=0, le=5000)


# ---------- Utilities ----------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def start_of_today_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def start_of_week_utc(now: datetime) -> datetime:
    # ISO week: Monday 00:00 UTC
    monday = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=now.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def current_user(request: Request, db: Session) -> Optional[Player]:
    email = request.session.get("user_email")
    if not email:
        return None
    return db.execute(select(Player).where(func.lower(Player.email) == email.lower())).scalar_one_or_none()


def query_leaderboard(db: Session, period: Literal["all", "today", "week"]) -> list[dict]:
    """Aggregate totals + best single-round per player across the selected period."""
    since: Optional[datetime] = None
    now = utcnow()
    if period == "today":
        since = start_of_today_utc(now)
    elif period == "week":
        since = start_of_week_utc(now)

    stmt = (
        select(
            Player.name.label("player_name"),
            func.count(ScoreEntry.id).label("entries"),
            func.coalesce(func.sum(ScoreEntry.total_score), 0).label("total_score"),
            func.avg(ScoreEntry.total_score).label("avg_score"),
            func.max(ScoreEntry.round1).label("max_r1"),
            func.max(ScoreEntry.round2).label("max_r2"),
            func.max(ScoreEntry.round3).label("max_r3"),
        )
        .join(ScoreEntry, ScoreEntry.player_id == Player.id)
    )
    if since is not None:
        stmt = stmt.where(ScoreEntry.played_at >= since)

    stmt = stmt.group_by(Player.id).order_by(func.sum(ScoreEntry.total_score).desc())

    rows = db.execute(stmt).all()
    out: list[dict] = []
    for idx, r in enumerate(rows, start=1):
        best_round = max(int(r.max_r1 or 0), int(r.max_r2 or 0), int(r.max_r3 or 0))
        out.append(
            {
                "rank": idx,
                "player_name": r.player_name,
                "count": int(r.entries or 0),
                "total_score": int(r.total_score or 0),
                "average_score": float(r.avg_score or 0.0),
                "max_round": best_round,
            }
        )
    return out


# ---------- Pages --------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def leaderboard_page(request: Request, db: Session = Depends(get_db)):
    rows_all = query_leaderboard(db, "all")
    rows_week = query_leaderboard(db, "week")
    rows_today = query_leaderboard(db, "today")
    saved = request.query_params.get("saved") == "1"
    me = current_user(request, db)
    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "saved": saved,
            "rows_all": rows_all,
            "rows_week": rows_week,
            "rows_today": rows_today,
            "me": me,
        },
    )


@app.get("/submit", response_class=HTMLResponse)
async def submit_form(request: Request, db: Session = Depends(get_db)):
    """Submit form (requires login). Shows daily limit message if already submitted today."""
    me = current_user(request, db)
    if not me:
        return templates.TemplateResponse("login_required.html", {"request": request})

    today = start_of_today_utc(utcnow())
    existing = db.execute(
        select(ScoreEntry.id).where(ScoreEntry.player_id == me.id, ScoreEntry.played_at >= today)
    ).first()
    limit_reached = existing is not None

    return templates.TemplateResponse("submit.html", {"request": request, "me": me, "limit_reached": limit_reached})


@app.post("/submit")
async def submit_form_post(
    request: Request,
    round1: int = Form(...),
    round2: int = Form(...),
    round3: int = Form(...),
    db: Session = Depends(get_db),
):
    """Handle submission. Enforces one submission per user per UTC day."""
    me = current_user(request, db)
    if not me:
        return RedirectResponse(url="/login?next=%2Fsubmit", status_code=303)

    today = start_of_today_utc(utcnow())
    already = db.execute(
        select(ScoreEntry.id).where(ScoreEntry.player_id == me.id, ScoreEntry.played_at >= today)
    ).first()
    if already:
        return RedirectResponse(url="/submit?limit=1", status_code=303)

    # Validate rounds
    try:
        r1 = int(round1)
        r2 = int(round2)
        r3 = int(round3)
    except Exception:
        raise HTTPException(400, detail="Scores must be integers")
    if any(x < 0 or x > 5000 for x in (r1, r2, r3)):
        raise HTTPException(400, detail="Scores must be between 0 and 5000")

    total = r1 + r2 + r3
    entry = ScoreEntry(
        player_id=me.id,
        played_at=utcnow(),
        round1=r1,
        round2=r2,
        round3=r3,
        total_score=total,
    )
    db.add(entry)
    db.commit()
    return RedirectResponse(url="/?saved=1", status_code=303)


# ---------- Auth: Register / Login / Logout -----------------------------------
@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
async def register_post(request: Request, db: Session = Depends(get_db), email: str = Form(...), name: str = Form(...)):
    """Create or update a player by email; tolerant of legacy DBs with UNIQUE(name)."""
    email = email.strip()
    name = name.strip()
    if not email or "@" not in email:
        raise HTTPException(400, detail="Valid email required")
    if not name:
        raise HTTPException(400, detail="Name is required")

    # 1) Try by email
    player = db.execute(select(Player).where(func.lower(Player.email) == email.lower())).scalar_one_or_none()
    if player:
        if player.name != name:
            player.name = name
            db.add(player)
            db.commit()
    else:
        # 2) Reuse by name (for DBs where name is UNIQUE)
        by_name = db.execute(select(Player).where(func.lower(Player.name) == name.lower())).scalar_one_or_none()
        if by_name:
            by_name.email = email
            db.add(by_name)
            db.commit()
            player = by_name
        else:
            # 3) Insert new; if UNIQUE(name) exists, update that row instead
            try:
                player = Player(email=email, name=name)
                db.add(player)
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.execute(
                    select(Player).where(func.lower(Player.name) == name.lower())
                ).scalar_one_or_none()
                if existing:
                    existing.email = email
                    db.add(existing)
                    db.commit()
                    player = existing
                else:
                    raise

    request.session["user_email"] = email
    request.session["user_name"] = player.name
    return RedirectResponse(url="/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_post(request: Request, db: Session = Depends(get_db), email: str = Form(...)):
    email = email.strip()
    player = db.execute(select(Player).where(func.lower(Player.email) == email.lower())).scalar_one_or_none()
    if not player:
        return RedirectResponse(url=f"/register?email={email}", status_code=303)
    request.session["user_email"] = email
    request.session["user_name"] = player.name
    next_url = request.query_params.get("next") or "/"
    return RedirectResponse(url=next_url, status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ---------- Optional JSON API --------------------------------------------------
@app.get("/api/leaderboard")
async def api_leaderboard(period: Literal["all", "today", "week"] = "all", db: Session = Depends(get_db)):
    return query_leaderboard(db, period)


@app.post("/api/submit_entry")
async def api_submit_entry(payload: SubmitEntryIn, db: Session = Depends(get_db)):
    """Legacy JSON API by name; also enforces one submission per UTC day."""
    player = db.execute(select(Player).where(func.lower(Player.name) == payload.player_name.lower())).scalar_one_or_none()
    if not player:
        player = Player(name=payload.player_name)
        db.add(player)
        db.flush()

    today = start_of_today_utc(utcnow())
    exists = db.execute(
        select(ScoreEntry.id).where(ScoreEntry.player_id == player.id, ScoreEntry.played_at >= today)
    ).first()
    if exists:
        raise HTTPException(409, detail="Already submitted today")

    total = int(payload.round1) + int(payload.round2) + int(payload.round3)
    entry = ScoreEntry(
        player_id=player.id,
        played_at=utcnow(),
        round1=int(payload.round1),
        round2=int(payload.round2),
        round3=int(payload.round3),
        total_score=total,
    )
    db.add(entry)
    db.commit()
    return {"ok": True, "entry_id": entry.id, "total": total}


@app.get("/health")
async def health():
    return {"ok": True, "time": utcnow().isoformat()}
