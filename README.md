
# GeoGuessr Leaderboard — v6.3 (Postgres-ready)

- Uses `DATABASE_URL` for Postgres (falls back to local SQLite file if not set).
- No SQLite-only PRAGMA calls; startup is DB-agnostic.
- Global board is stats-only; submissions go to specific boards.
- Create board in navbar (only when logged in).

## Run locally (SQLite)
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

## Run with Postgres
Set env `DATABASE_URL`. Examples:
- `postgres://USER:PASSWORD@HOST:5432/DBNAME`
- `postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME`

If TLS is required, append `?sslmode=require`:
`postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require`

Then:
```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000
