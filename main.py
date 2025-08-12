from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import os

from strava_client import (
    get_weekly_summary,
    get_weekly_details,
    resolve_types,
)

app = FastAPI(title="Coach Triathlon API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _get_token(override: str | None) -> str:
    """
    1) Si un token est passé en query, on l'utilise.
    2) Sinon on prend la variable d'env ACCESS_TOKEN (Render > Environment).
    """
    token = override or os.getenv("ACCESS_TOKEN")
    if not token:
        # On rend l’erreur claire côté client GPT
        raise ValueError(
            "Missing access_token. Provide ?access_token=... or set ACCESS_TOKEN env var."
        )
    return token

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/weekly-stats")
def weekly_stats(
    access_token: str | None = Query(default=None, description="Strava OAuth access_token (optionnel si défini en env)"),
    types: str = Query(
        default="tri",
        description="Filtre des types d'activités: 'tri' (par défaut) | 'endurance' | 'all' | liste CSV (ex: 'Ride,Run,Swim,Workout,WeightTraining')"
    ),
):
    token = _get_token(access_token)
    allowed = resolve_types(types)
    return get_weekly_summary(token, allowed)

@app.get("/weekly-details")
def weekly_details(
    access_token: str | None = Query(default=None, description="Strava OAuth access_token (optionnel si défini en env)"),
    with_streams: bool = Query(default=False, description="Inclure les séries temporelles (FC, vitesse) si dispo"),
    types: str = Query(
        default="tri",
        description="Filtre des types d'activités: 'tri' | 'endurance' | 'all' | liste CSV personnalisée"
    ),
):
    token = _get_token(access_token)
    allowed = resolve_types(types)
    return get_weekly_details(token, allowed, with_streams=with_streams)
