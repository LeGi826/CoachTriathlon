from typing import Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from strava_client import get_weekly_summary, get_weekly_details

app = FastAPI(title="CoachTriathlon API")

# CORS (autoriser les appels depuis ton GPT)
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
def weekly_stats(access_token: Optional[str] = Query(default=None)):
    """
    Résumé hebdo simple (km, temps total, nb d'activités)
    access_token est optionnel (refresh automatique côté serveur si absent/expiré).
    """
    return get_weekly_summary(access_token)

@app.get("/weekly-details")
def weekly_details(
    access_token: Optional[str] = Query(default=None),
    with_streams: bool = Query(default=False)
):
    """
    Détails hebdo : résumé, agrégats par sport (incl. cardio), liste d'activités,
    et, si with_streams=True, séries temporelles FC/vitesse (si autorisées).
    """
    return get_weekly_details(access_token, with_streams=with_streams)
