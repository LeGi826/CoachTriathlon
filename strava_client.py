import os
import requests
from datetime import datetime, timedelta
from typing import Optional

# Base API
_API = "https://www.strava.com/api/v3"
_TRI_TYPES = {"Ride", "Run", "Swim"}

# ---------- OAuth helpers ----------

def _refresh_access_token() -> Optional[str]:
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        return None

    url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        resp = requests.post(url, data=payload, timeout=20)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None

    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token")
    if new_refresh:
        # stocké en RAM (process), suffisant pour Render
        os.environ["STRAVA_REFRESH_TOKEN"] = new_refresh
    return new_access

def _get_access_token(maybe_from_query: Optional[str]) -> Optional[str]:
    if maybe_from_query:
        return maybe_from_query
    env_token = os.getenv("ACCESS_TOKEN")
    if env_token:
        return env_token
    return _refresh_access_token()

# ---------- période (depuis lundi) ----------

def _since_monday_ts() -> int:
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday())
    return int(last_monday.timestamp())

# ---------- filtrage activités ----------

def _parse_types(types_mode: str):
    """
    Retourne :
      - "all" si types_mode == "all"
      - _TRI_TYPES si types_mode vide ou "tri"
      - un set de types parsé depuis 'Type1,Type2,...'
    """
    if not types_mode or types_mode == "tri":
        return _TRI_TYPES
    if types_mode == "all":
        return "all"
    wanted = {t.strip() for t in types_mode.split(",") if t.strip()}
    return wanted or _TRI_TYPES

def _filter_acts(data: list[dict], types_mode: str) -> list[dict]:
    parsed = _parse_types(types_mode)
    if parsed == "all":
        return data[:]  # toutes les activités
    return [a for a in data if (a.get("type") in parsed)]

# ---------- formatage activité ----------

def _fmt_activity(a: dict) -> dict:
    dist_km = float(a.get("distance", 0.0)) / 1000.0
    mov_s = int(a.get("moving_time", 0))
    elev = float(a.get("total_elevation_gain", 0.0) or 0.0)
    avg_spd = a.get("average_speed")   # m/s
    max_spd = a.get("max_speed")       # m/s

    def kmh(mps):
        return round(mps * 3.6, 1) if (mps is not None) else None

    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "type": a.get("type"),
        "start_date_local": a.get("start_date_local"),
        "distance_km": round(dist_km, 2),
        "moving_time_s": mov_s,
        "elapsed_time_s": int(a.get("elapsed_time", 0)),
        "elev_gain_m": round(elev, 1),
        "avg_speed_kmh": kmh(avg_spd),
        "max_speed_kmh": kmh(max_spd),
        "avg_heartrate": a.get("average_heartrate"),
        "max_heartrate": a.get("max_heartrate"),
        "suffer_score": a.get("suffer_score"),
        "trainer": a.get("trainer"),
        "commute": a.get("commute"),
    }

# ---------- agrégats ----------

def _group_by_sport(acts: list[dict]) -> dict:
    out: dict[str, dict] = {}

    for a in acts:
        sport = a.get("type") or "Other"
        g = out.setdefault(sport, {
            "count": 0,
            "total_km": 0.0,
            "total_time_s": 0,
            "elev_gain_m": 0.0,
            # cardio agrégé
            "sum_avg_hr": 0.0,
            "with_hr_count": 0,
            "max_hr": 0.0,
        })
        g["count"] += 1
        g["total_km"] += float(a.get("distance_km") or 0.0)
        g["total_time_s"] += int(a.get("m
