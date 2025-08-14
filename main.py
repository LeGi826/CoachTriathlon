from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
from typing import Optional

from strava_client import (
    get_weekly_summary,
    get_weekly_details,
    get_weekly_analysis,
)

app = FastAPI(
    title="CoachTriathlon API",
    version="1.3.0",
    description="Endpoints d'agrégation Strava pour CoachTriathlon (hebdo + cardio + récup), avec streams downsample.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Helpers ----------

def _get_token(query_token: Optional[str]) -> str:
    """
    1) ?access_token=
    2) ACCESS_TOKEN (env)
    3) sinon "" => le client backend tentera le refresh STRAVA_* automatiquement.
    """
    if query_token:
        return query_token
    env_token = os.getenv("ACCESS_TOKEN")
    if env_token:
        return env_token
    return ""


# ---------- Endpoints ----------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/weekly-stats")
def weekly_stats(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    types: str = Query("all", description="Liste CSV ou 'all'."),
):
    token = _get_token(access_token)
    try:
        data = get_weekly_summary(access_token=token, types=types)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": "weekly_stats_failed", "detail": str(e)}, status_code=500)


@app.get("/weekly-details")
def weekly_details(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    types: str = Query("all", description="Liste CSV ou 'all'."),
    streams_mode: str = Query("none", description="'none' | 'summary' | 'full'"),
    max_points: int = Query(1500, ge=100, le=10000, description="Cap max points par série quand streams_mode=full"),
    compute_decoupling: bool = Query(False, description="Décorrélation HR (Run/Ride) si streams dispo"),
    hrmax: Optional[int] = Query(None, description="FC max (bpm) pour zones (sinon estimée/fallback)"),
    hrrest: Optional[int] = Query(None, description="FC repos (bpm) pour Karvonen si utilisé côté analysis"),
):
    """
    Détails hebdo. streams_mode:
      - none    : pas de séries
      - summary : pas de séries, mais temps en zones + (optionnel) decoupling calculés via séries si dispo
      - full    : séries HR/vitesse renvoyées (downsample max_points) + stats
    """
    token = _get_token(access_token)
    try:
        data = get_weekly_details(
            access_token=token,
            types=types,
            streams_mode=streams_mode,
            max_points=max_points,
            compute_decoupling=compute_decoupling,
            hrmax=hrmax,
            hrrest=hrrest,
        )
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": "weekly_details_failed", "detail": str(e)}, status_code=500)


@app.get("/weekly-analysis")
def weekly_analysis(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    types: str = Query("all", description="Liste CSV ou 'all'."),
    with_streams: bool = Query(True, description="Inclure les streams pour zones/decoupling (côté serveur)"),
    zone_model: str = Query("percent_max", description="'percent_max' ou 'karvonen'"),
    hrmax: Optional[int] = Query(None, description="FC max (bpm) — sinon estimée"),
    hrrest: Optional[int] = Query(None, description="FC repos (bpm) — utile pour Karvonen (défaut 60)"),
    compute_decoupling: bool = Query(True, description="Calcule l'HR decoupling si streams dispo"),
):
    """
    Analyse cardio hebdo (compacte) :
      - TRIMP total, temps en zones, monotony/strain, decoupling.
      - Ne renvoie pas de streams bruts => réponses légères pour le GPT.
    """
    token = _get_token(access_token)
    try:
        data = get_weekly_analysis(
            access_token=token,
            types=types,
            with_streams=with_streams,
            zone_model=zone_model,
            hrmax=hrmax,
            hrrest=hrrest,
            compute_decoupling=compute_decoupling,
        )
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": "weekly_analysis_failed", "detail": str(e)}, status_code=500)
