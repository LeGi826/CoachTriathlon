from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
from typing import Optional

from strava_client import (
    get_weekly_summary,
    get_weekly_details,
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
    3) sinon il n'est pas requis si STRAVA_REFRESH_TOKEN est défini (rafraîchissement automatique).
    """
    if query_token:
        return query_token

    env_token = os.getenv("ACCESS_TOKEN")
    if env_token:
        return env_token

    # Si pas de token direct, on laissera strava_client rafraîchir via STRAVA_REFRESH_TOKEN.
    # On renvoie une chaîne vide pour signifier "utilise le refresh token".
    return ""


def _get_hr_inputs(hr_rest: Optional[float], hr_max: Optional[float]):
    """
    Récupère HRrest/HRmax depuis:
    - query string si fournis
    - sinon ENV HR_RESTING / HR_MAX
    - sinon None (les calculs de TRIMP s'adapteront en conséquence)
    """
    if hr_rest is None:
        env_rest = os.getenv("HR_RESTING")
        if env_rest:
            try:
                hr_rest = float(env_rest)
            except ValueError:
                hr_rest = None
    if hr_max is None:
        env_max = os.getenv("HR_MAX")
        if env_max:
            try:
                hr_max = float(env_max)
            except ValueError:
                hr_max = None
    return hr_rest, hr_max


# ---------- Endpoints ----------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/weekly-stats")
def weekly_stats(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    week_start: Optional[str] = Query(None, description="YYYY-MM-DD (lundi). Par défaut: ce lundi."),
):
    """
    Stats hebdo compactes (tous sports) + distribution par type.
    """
    token = _get_token(access_token)
    try:
        data = get_weekly_summary(access_token=token, week_start=week_start)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": "weekly_stats_failed", "detail": str(e)}, status_code=500)


@app.get("/weekly-details")
def weekly_details(
    access_token: Optional[str] = Query(None, description="Token Strava (optionnel si refresh token configuré)"),
    with_streams: bool = Query(False, description="Inclure les streams HR/vitesse (peut être lourd)"),
    compute_decoupling: bool = Query(False, description="Calcule l'HR decoupling si streams dispo"),
    hr_rest: Optional[float] = Query(None, description="FC repos (bpm) — sinon HR_RESTING env"),
    hr_max: Optional[float] = Query(None, description="FC max (bpm) — sinon HR_MAX env"),
    week_start: Optional[str] = Query(None, description="YYYY-MM-DD (lundi). Par défaut: ce lundi."),
):
    """
    Détails complets hebdo, cardio, agrégats par sport, TRIMP, monotony/strain.
    """
    token = _get_token(access_token)
    hr_rest, hr_max = _get_hr_inputs(hr_rest, hr_max)
    try:
        data = get_weekly_details(
            access_token=token,
            include_streams=with_streams,
            compute_decoupling=compute_decoupling,
            hr_rest=hr_rest,
            hr_max=hr_max,
            week_start=week_start,
        )
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": "weekly_details_failed", "detail": str(e)}, status_code=500)
