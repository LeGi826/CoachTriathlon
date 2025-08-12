import os
import requests
from datetime import datetime, timedelta

# Cache simple en mémoire pour éviter de redemander le token trop souvent
_ACCESS_TOKEN_CACHE = None

def _refresh_access_token():
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        return None, {"error": "missing_env", "hint": "Set STRAVA_CLIENT_ID/SECRET/REFRESH_TOKEN on Render"}

    url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    resp = requests.post(url, data=payload, timeout=20)
    if resp.status_code != 200:
        try:
            return None, {"error": "refresh_failed", "status_code": resp.status_code, "detail": resp.json()}
        except Exception:
            return None, {"error": "refresh_failed", "status_code": resp.status_code, "detail": resp.text}

    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token")

    # Mémorise en RAM (durera tant que l’instance Render reste up)
    global _ACCESS_TOKEN_CACHE
    _ACCESS_TOKEN_CACHE = new_access

    # Met à jour le refresh_token en RAM (Render ne peut pas être modifié à chaud)
    if new_refresh:
        os.environ["STRAVA_REFRESH_TOKEN"] = new_refresh

    return new_access, {"refreshed": True}

def _get_access_token():
    # 1) Token déjà en cache mémoire ?
    global _ACCESS_TOKEN_CACHE
    if _ACCESS_TOKEN_CACHE:
        return _ACCESS_TOKEN_CACHE

    # 2) Sinon, tenter avec ACCESS_TOKEN si présent (optionnel)
    access = os.getenv("ACCESS_TOKEN")
    if access:
        _ACCESS_TOKEN_CACHE = access
        return access

    # 3) Sinon, rafraîchir via refresh_token
    new_access, _ = _refresh_access_token()
    return new_access

def get_weekly_summary(_token_from_query: str | None):
    token = _token_from_query or _get_access_token()
    if not token:
        return {"error": "no_access_token", "hint": "Missing ACCESS_TOKEN or REFRESH flow failed."}

    # Fenêtre depuis lundi
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday())
    after = int(last_monday.timestamp())

    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"after": after, "per_page": 100}

    resp = requests.get(url, headers=headers, params=params, timeout=20)

    # Si expiré/invalid → refresh et retry 1 fois
    if resp.status_code in (401, 403):
        new_access, info = _refresh_access_token()
        if not new_access:
            return {"error": "strava_token_invalid", "detail": info}
        headers = {"Authorization": f"Bearer {new_access}"}
        resp = requests.get(url, headers=headers, params=params, timeout=20)

    if resp.status_code != 200:
        try:
            detail = resp.json()
        except Exception:
            detail = {"text": resp.text}
        return {"error": "strava_api_error", "status_code": resp.status_code, "detail": detail}

    activities = resp.json()
    total_distance = 0.0
    total_duration = 0
    count = 0

    for act in activities:
        if act.get("type") in ("Ride", "Run", "Swim"):
            total_distance += float(act.get("distance", 0))
            total_duration += int(act.get("moving_time", 0))
            count += 1

    return {
        "total_km": round(total_distance / 1000, 1),
        "total_time_h": round(total_duration / 3600, 2),
        "rides": count
    }
