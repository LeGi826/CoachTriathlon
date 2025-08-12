from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import os

from strava_client import (
    get_weekly_summary,
    get_weekly_details,
    get_weekly_analysis,
)

app = FastAPI(title="CoachTriathlon API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_token(query_token: str | None) -> str:
    """
    Récupère le token d'accès Strava à partir de la query (?access_token=...)
    ou depuis la variable d'env ACCESS_TOKEN. Si absent => lève une erreur explicite.
    """
    if query_token and query_token.strip():
        return query_token.strip()
    env_token = os.getenv("ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token
    raise ValueError(
        "Missing access_token. Provide ?access_token=... or set ACCESS_TOKEN env var."
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/weekly-stats")
def weekly_stats(
    access_token: str | None = Query(default=None),
    types: str = Query(default="all", description="Liste de types séparés par des virgules (ex: Ride,Run,Swim,WeightTraining) ou 'all'"),
):
    """
    Retourne un résumé hebdo simple (total km, total heures, nombre de séances, décompte par type)
    """
    token = _get_token(access_token)
    return get_weekly_summary(token, types=types)


@app.get("/weekly-details")
def weekly_details(
    access_token: str | None = Query(default=None),
    types: str = Query(default="all"),
    with_streams: bool = Query(default=False),
):
    """
    Détails hebdo par séance, + agrégats par sport; option pour inclure les streams (heartrate, velocity_smooth)
    """
    token = _get_token(access_token)
    return get_weekly_details(token, types=types, with_streams=with_streams)


@app.get("/weekly-analysis")
def weekly_analysis(
    access_token: str | None = Query(default=None),
    types: str = Query(default="all"),
    with_streams: bool = Query(default=True, description="Recommandé: True pour une analyse plus fine"),
    zone_model: str = Query(default="percent_max", description="'percent_max' (par défaut) ou 'karvonen'"),
    hrmax: int | None = Query(default=None, description="Fréquence cardiaque max connue (bpm). Si vide, estimation automatique."),
    lthr: int | None = Query(default=None, description="Seuil lactique (bpm) — utile pour certains modèles."),
):
    """
    Analyse cardio hebdomadaire :
      - Temps passé dans 5 zones
      - TRIMP par séance et total hebdo
      - Intensité moyenne hebdo
      - Estimation automatique de HRmax si non fourni
    """
    token = _get_token(access_token)
    return get_weekly_analysis(
        token,
        types=types,
        with_streams=with_streams,
        zone_model=zone_model,
        hrmax=hrmax,
        lthr=lthr,
    )
