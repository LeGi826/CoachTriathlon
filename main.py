import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from strava_client import get_weekly_summary

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/debug-token")
def debug_token():
    has_token = bool(os.getenv("ACCESS_TOKEN"))
    return {"ACCESS_TOKEN_present": has_token}

@app.get("/weekly-stats")
def weekly_stats(access_token: str | None = Query(default=None)):
    token = access_token or os.getenv("ACCESS_TOKEN")
    if not token:
        return {"error": "missing_access_token",
                "hint": "Set ACCESS_TOKEN on Render or pass ?access_token=..."}
    return get_weekly_summary(token)
