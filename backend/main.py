from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Literal, List

from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, Integer, String, DateTime, ForeignKey, UniqueConstraint,
    select, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session

# ---------- DB setup (SQLite) --------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_URL = f"sqlite:///{ROOT.parent / 'geoguessr.db'}"
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

class Base(DeclarativeBase):
    pass

class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    entries: Mapped[List["ScoreEntry"]] = relationship(back_populates="player")

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

# ---------- FastAPI + Jinja ----------------------------------------------------
app = FastAPI(title="GeoGuessr Leaderboard", version="0.3.0")

static_dir = ROOT / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=str(ROOT / "templates"))

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Schemas (optional JSON API) ---------------------------------------
class SubmitEntryIn(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=80)
    round1: int = Field(..., ge=0, le=5000)
    round2: int = Field(..., ge=0, le=5000)
    round3: int = Field(..., ge=0, le=5000)

# ---------- Helpers ------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def start_of_week_utc(now: datetime) -> datetime:
    # ISO week: Monday = 0
    weekday = now.weekday()  # 0..6
    monday = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=weekday)
    # Truncate to midnight
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)

def query_leaderboard(db: Session, period: Literal["all", "today", "7d", "30d", "week"]) -> list[dict]:
    since: Optional[datetime] = None
    now = utcnow()
    if period == "today":
        since = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    elif period == "7d":
        since = now - timedelta(days=7)
    elif period == "30d":
        since = now - timedelta(days=30)
    elif period == "week":
        since = start_of_week_utc(now)

    # Aggregate totals per player across entries in the period
    stmt = (
        select(
            Player.name.label("player_name"),
            func.count(ScoreEntry.id).label("entries"),
            func.coalesce(func.sum(ScoreEntry.total_score), 0).label("total_score"),
            func.avg(ScoreEntry.total_score).label("avg_score"),
        )
        .join(ScoreEntry, ScoreEntry.player_id == Player.id)
    )
    if since is not None:
        stmt = stmt.where(ScoreEntry.played_at >= since)

    stmt = stmt.group_by(Player.id).order_by(func.sum(ScoreEntry.total_score).desc())

    rows = db.execute(stmt).all()
    out: list[dict] = []
    for idx, r in enumerate(rows, start=1):
        out.append({
            "rank": idx,
            "player_name": r.player_name,
            "count": int(r.entries or 0),
            "total_score": int(r.total_score or 0),
            "average_score": float(r.avg_score or 0.0),
        })
    return out

# ---------- HTML routes --------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def leaderboard_page(request: Request, db: Session = Depends(get_db)):
    rows_all = query_leaderboard(db, "all")
    rows_week = query_leaderboard(db, "week")
    rows_today = query_leaderboard(db, "today")
    saved = request.query_params.get("saved") == "1"
    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "saved": saved,
        "rows_all": rows_all,
        "rows_week": rows_week,
        "rows_today": rows_today,
    })

@app.get("/submit", response_class=HTMLResponse)
async def submit_form(request: Request):
    return templates.TemplateResponse("submit.html", {"request": request})

@app.post("/submit")
async def submit_form_post(
    player_name: str = Form(...),
    round1: int = Form(...),
    round2: int = Form(...),
    round3: int = Form(...),
    db: Session = Depends(get_db),
):
    # Upsert player
    player = db.execute(select(Player).where(func.lower(Player.name) == player_name.lower())).scalar_one_or_none()
    if not player:
        player = Player(name=player_name.strip())
        db.add(player)
        db.flush()

    # Validate rounds
    try:
        r1 = int(round1); r2 = int(round2); r3 = int(round3)
    except Exception:
        raise HTTPException(400, detail="Scores must be integers")

    if any(x < 0 or x > 5000 for x in (r1, r2, r3)):
        raise HTTPException(400, detail="Scores must be between 0 and 5000")

    total = r1 + r2 + r3
    entry = ScoreEntry(
        player_id=player.id,
        played_at=utcnow(),
        round1=r1,
        round2=r2,
        round3=r3,
        total_score=total,
    )
    db.add(entry)
    db.commit()

    return RedirectResponse(url="/?saved=1", status_code=303)

# ---------- Optional JSON API --------------------------------------------------
@app.get("/api/leaderboard")
async def api_leaderboard(period: Literal["all", "today", "7d", "30d", "week"] = "all", db: Session = Depends(get_db)):
    return query_leaderboard(db, period)

@app.post("/api/submit_entry")
async def api_submit_entry(payload: SubmitEntryIn, db: Session = Depends(get_db)):
    player = db.execute(select(Player).where(func.lower(Player.name) == payload.player_name.lower())).scalar_one_or_none()
    if not player:
        player = Player(name=payload.player_name.strip())
        db.add(player)
        db.flush()

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
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}
