from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Literal, List

from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Integer, String, DateTime, ForeignKey, select, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parent
DB_URL = f"sqlite:///{ROOT.parent / 'geoguessr.db'}"
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

class Base(DeclarativeBase): pass

class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    entries: Mapped[List['ScoreEntry']] = relationship(back_populates="player")

class ScoreEntry(Base):
    __tablename__ = "score_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    round1: Mapped[int] = mapped_column(Integer)
    round2: Mapped[int] = mapped_column(Integer)
    round3: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[int] = mapped_column(Integer)
    player: Mapped[Player] = relationship(back_populates="entries")

Base.metadata.create_all(bind=engine)
with engine.connect() as conn:
    cols = [row[1] for row in conn.execute(text("PRAGMA table_info(players)"))]
    if "email" not in cols:
        conn.execute(text("ALTER TABLE players ADD COLUMN email VARCHAR(255)"))
        conn.commit()
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_players_email ON players(email)"))
    conn.commit()

app = FastAPI(title="GeoGuessr Leaderboard", version="0.4.3")
app.add_middleware(SessionMiddleware, secret_key="change-me-please-very-secret")

static_dir = ROOT / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

def get_db() -> Session:
    db = SessionLocal()
    try: yield db
    finally: db.close()

class SubmitEntryIn(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=80)
    round1: int = Field(..., ge=0, le=5000)
    round2: int = Field(..., ge=0, le=5000)
    round3: int = Field(..., ge=0, le=5000)

def utcnow() -> datetime: return datetime.now(timezone.utc)
def start_of_week_utc(now: datetime) -> datetime:
    monday = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=now.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)

def current_user(request: Request, db: Session) -> Optional[Player]:
    email = request.session.get("user_email")
    if not email: return None
    return db.execute(select(Player).where(func.lower(Player.email) == email.lower())).scalar_one_or_none()

def query_leaderboard(db: Session, period: Literal["all", "today", "week"]) -> list[dict]:
    since = None
    now = utcnow()
    if period == "today":
        since = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    elif period == "week":
        since = start_of_week_utc(now)

    stmt = (select(Player.name.label("player_name"),
                   func.count(ScoreEntry.id).label("entries"),
                   func.coalesce(func.sum(ScoreEntry.total_score), 0).label("total_score"),
                   func.avg(ScoreEntry.total_score).label("avg_score"))
            .join(ScoreEntry, ScoreEntry.player_id == Player.id))
    if since is not None:
        stmt = stmt.where(ScoreEntry.played_at >= since)
    stmt = stmt.group_by(Player.id).order_by(func.sum(ScoreEntry.total_score).desc())

    out = []
    for idx, r in enumerate(db.execute(stmt).all(), start=1):
        out.append({"rank": idx, "player_name": r.player_name, "count": int(r.entries or 0),
                    "total_score": int(r.total_score or 0), "average_score": float(r.avg_score or 0.0)})
    return out

@app.get("/", response_class=HTMLResponse)
async def leaderboard_page(request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    return templates.TemplateResponse("leaderboard.html", {"request": request, "saved": request.query_params.get("saved") == "1",
        "rows_all": query_leaderboard(db, "all"),
        "rows_week": query_leaderboard(db, "week"),
        "rows_today": query_leaderboard(db, "today"),
        "me": me})

@app.get("/submit", response_class=HTMLResponse)
async def submit_form(request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if not me: return templates.TemplateResponse("login_required.html", {"request": request})
    return templates.TemplateResponse("submit.html", {"request": request, "me": me})

@app.post("/submit")
async def submit_form_post(request: Request, round1: int = Form(...), round2: int = Form(...), round3: int = Form(...),
                           db: Session = Depends(get_db)):
    me = current_user(request, db)
    if not me: return RedirectResponse(url="/login?next=%2Fsubmit", status_code=303)
    r1, r2, r3 = int(round1), int(round2), int(round3)
    if any(x < 0 or x > 5000 for x in (r1, r2, r3)):
        raise HTTPException(400, detail="Scores must be between 0 and 5000")
    db.add(ScoreEntry(player_id=me.id, played_at=utcnow(), round1=r1, round2=r2, round3=r3, total_score=r1+r2+r3))
    db.commit()
    return RedirectResponse(url="/?saved=1", status_code=303)

@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request): return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register_post(request: Request, db: Session = Depends(get_db), email: str = Form(...), name: str = Form(...)):
    email, name = email.strip(), name.strip()
    if not email or "@" not in email: raise HTTPException(400, detail="Valid email required")
    if not name: raise HTTPException(400, detail="Name is required")

    # 1) Try by email first
    player = db.execute(select(Player).where(func.lower(Player.email) == email.lower())).scalar_one_or_none()
    if player:
        if player.name != name: player.name = name; db.add(player); db.commit()
    else:
        # 2) If legacy DB enforces UNIQUE(name), reuse the row with the same name
        by_name = db.execute(select(Player).where(func.lower(Player.name) == name.lower())).scalar_one_or_none()
        if by_name:
            by_name.email = email
            db.add(by_name)
            db.commit()
            player = by_name
        else:
            # 3) Insert new row, with safety net against unexpected unique constraints
            try:
                player = Player(email=email, name=name)
                db.add(player); db.commit()
            except IntegrityError:
                db.rollback()
                # Fallback: fetch existing by name and update email
                existing = db.execute(select(Player).where(func.lower(Player.name) == name.lower())).scalar_one_or_none()
                if existing:
                    existing.email = email
                    db.add(existing); db.commit()
                    player = existing
                else:
                    raise

    request.session["user_email"] = email
    request.session["user_name"] = player.name
    return RedirectResponse(url="/", status_code=303)

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request): return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_post(request: Request, db: Session = Depends(get_db), email: str = Form(...)):
    email = email.strip()
    player = db.execute(select(Player).where(func.lower(Player.email) == email.lower())).scalar_one_or_none()
    if not player: return RedirectResponse(url=f"/register?email={email}", status_code=303)
    request.session["user_email"] = email; request.session["user_name"] = player.name
    return RedirectResponse(url=request.query_params.get("next") or "/", status_code=303)

@app.get("/logout")
async def logout(request: Request): request.session.clear(); return RedirectResponse(url="/", status_code=303)

@app.get("/api/leaderboard")
async def api_leaderboard(period: Literal["all", "today", "week"] = "all", db: Session = Depends(get_db)):
    return query_leaderboard(db, period)

class SubmitEntryIn(BaseModel):
    player_name: str; round1: int; round2: int; round3: int

@app.post("/api/submit_entry")
async def api_submit_entry(payload: SubmitEntryIn, db: Session = Depends(get_db)):
    player = db.execute(select(Player).where(func.lower(Player.name) == payload.player_name.lower())).scalar_one_or_none()
    if not player: player = Player(name=payload.player_name); db.add(player); db.flush()
    total = int(payload.round1) + int(payload.round2) + int(payload.round3)
    db.add(ScoreEntry(player_id=player.id, played_at=utcnow(), round1=int(payload.round1), round2=int(payload.round2),
                      round3=int(payload.round3), total_score=total))
    db.commit()
    return {"ok": True}
