# GeoGuessr Team Leaderboard (Minimal, HTML + FastAPI)

Now with simple registration/login (email + name). Submit 3 rounds; total & timestamp are automatic.

## Quickstart
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
# open http://127.0.0.1:8000
```


**Note about old databases:** Some early versions created a UNIQUE constraint on `players.name`. v4.3 registration now reuses existing rows by name to avoid IntegrityError.
