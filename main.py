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
def weekly_stats(
    access_token: Optional[str] = Query(default=None),
    types: str = Query(
        default="tri",
        description="tri | all | liste ex: Ride,Run,Swim,WeightTraining"
    )
):
    """
    Résumé hebdo (km, temps total, nb de sessions) + compte par sport.
    - types='tri' (par défaut) : Ride/Run/Swim uniquement
    - types='all' : toutes les activités Strava
    - types='Ride,Run,...' : liste personnalisée
    """
    return get_weekly_summary(access_token, types=types)

@app.get("/weekly-details")
def weekly_details(
    access_token: Optional[str] = Query(default=None),
    with_streams: bool = Query(default=False),
    types: str = Query(
        default="tri",
        description="tri | all | liste ex: Ride,Run,Swim,WeightTraining"
    )
):
    """
    Détails hebdo :
      - summary (km/temps/sessions),
      - by_sport (incl. cardio agrégé),
      - activities (liste complète),
      - streams (FC/vitesse) si with_streams=True.
    Filtrage idem au endpoint /weekly-stats via 'types'.
    """
    return get_weekly_details(access_token, with_streams=with_streams, types=types)
