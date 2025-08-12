from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from strava_client import get_weekly_summary, get_weekly_details

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
    return get_weekly_summary(access_token)

@app.get("/weekly-details")
def weekly_details(
    access_token: str | None = Query(default=None),
    with_streams: bool = Query(default=False)
):
    # with_streams=True ajoute séries temporelles (FC/vitesse) si disponibles
    return get_weekly_details(access_token, with_streams=with_streams)
