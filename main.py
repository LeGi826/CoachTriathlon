from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from strava_client import get_weekly_summary

app = FastAPI(title="CoachTriathlon API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/weekly-stats")
def weekly_stats(access_token: str | None = Query(default=None)):
    # access_token est optionnel : si absent, on auto-refresh avec STRAVA_REFRESH_TOKEN
    return get_weekly_summary(access_token)
