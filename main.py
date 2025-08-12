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
    version="1.0.0",
    description="Endpoints d'agrégation Strava pour CoachTriathlon (hebdomadaire + cardio/récup).",
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
    Récupère un access_token Strava depuis:
    1) le paramètre d'URL ?access_token=
    2) la variable d'environnement ACCESS_TOKEN
    3) sinon chaîne vide -> on laisse strava_client tenter un refresh via STRAVA_REFRESH_TOKEN.
    """
    if query_token:
        return query_token
    env_token = os.getenv("ACCESS_TOKEN")
    if env_token:
        return env_token
    # Pas de token direct -> on renvoie "", strava_client fera un refresh automatique (401 -> refresh_token)
    return ""


# ---------- Endpoints ----------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/weekly-stats")
def weekly_stats(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    types: str = Query("all", description="Liste de types séparés par des virgules (ou 'all')."),
):
    """
    Stats hebdo compactes (tous sports) + distribution par type.
    """
    token = _get_token(access_token)
    try:
        data = get_weekly_summary(access_token=token, types=types)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": "weekly_stats_failed", "detail": str(e)}, status_code=500)


@app.get("/weekly-details")
def weekly_details(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    types: str = Query("all", description="Liste de types séparés par des virgules (ou 'all')."),
    with_streams: bool = Query(False, description="Inclure les streams HR/vitesse (peut être lourd)"),
):
    """
    Détails complets hebdo + agrégats par sport. (Cardio de base si HR présent).
    """
    token = _get_token(access_token)
    try:
        data = get_weekly_details(access_token=token, types=types, with_streams=with_streams)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": "weekly_details_failed", "detail": str(e)}, status_code=500)


@app.get("/weekly-analysis")
def weekly_analysis(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    types: str = Query("all", description="Liste de types séparés par des virgules (ou 'all')."),
    with_streams: bool = Query(True, description="Inclure les streams HR/vitesse pour zones/decoupling."),
    zone_model: str = Query("percent_max", description="'percent_max' ou 'karvonen'"),
    hrmax: Optional[int] = Query(None, description="FC max (bpm) — sinon estimée sur la semaine"),
    hrrest: Optional[int] = Query(None, description="FC repos (bpm) — utile pour Karvonen (défaut 60)"),
    compute_decoupling: bool = Query(True, description="Calcule l'HR decoupling si streams dispo"),
):
    """
    Analyse cardio hebdo:
    - TRIMP par séance + temps en zones
    - Récup (daily_trimp, trimp_by_type, monotony, strain)
    - HR decoupling (Run/Ride) si streams présents
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
