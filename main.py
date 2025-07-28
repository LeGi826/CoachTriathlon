from fastapi import FastAPI, Query
from strava_client import get_weekly_summary
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/weekly-stats")
def weekly_stats(access_token: str = Query(...)):
    return get_weekly_summary(access_token)
