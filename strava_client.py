import os
import requests
from datetime import datetime, timedelta

_API = "https://www.strava.com/api/v3"

def _refresh_access_token():
    cid = os.getenv("STRAVA_CLIENT_ID")
    csec = os.getenv("STRAVA_CLIENT_SECRET")
    rtok = os.getenv("STRAVA_REFRESH_TOKEN")
    if not (cid and csec and rtok):
        return None

    resp = requests.post(
        f"{_API.replace('/api/v3','')}/oauth/token",
        data={"client_id": cid, "client_secret": csec, "grant_type": "refresh_token", "refresh_token": rtok},
        timeout=20,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("refresh_token"):
        os.environ["STRAVA_REFRESH_TOKEN"] = data["refresh_token"]
    return data.get("access_token")

def _get_access_token():
    # essaie ACCESS_TOKEN sinon refresh
    tok = os.getenv("ACCESS_TOKEN")
    if tok:
        return tok
    return _refresh_access_token()

def _since_monday_ts():
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday())
    return int(last_monday.timestamp())

def _fmt_activity(a):
    # certains champs peuvent être absents selon tes autorisations et l’appareil
    dist_km = float(a.get("distance", 0)) / 1000.0
    mov_s = int(a.get("moving_time", 0))
    elev = a.get("total_elevation_gain", 0) or 0
    avg_spd = a.get("average_speed")  # m/s si présent
    max_spd = a.get("max_speed")
    def kmh(mps): return round(mps * 3.6, 1) if mps is not None else None

    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "type": a.get("type"),
        "start_date_local": a.get("start_date_local"),
        "distance_km": round(dist_km, 2),
        "moving_time_s": mov_s,
        "elapsed_time_s": int(a.get("elapsed_time", 0)),
        "elev_gain_m": round(float(elev), 1),
        "avg_speed_kmh": kmh(avg_spd),
        "max_speed_kmh": kmh(max_spd),
        "avg_heartrate": a.get("average_heartrate"),
        "max_heartrate": a.get("max_heartrate"),
        "suffer_score": a.get("suffer_score"),  # si dispo
        "trainer": a.get("trainer"),
        "commute": a.get("commute"),
    }

def _group_by_sport(acts):
    out = {}
    for a in acts:
        t = a["type"] or "Other"
        g = out.setdefault(t, {"count": 0, "total_km": 0.0, "total_time_s": 0, "elev_gain_m": 0.0})
        g["count"] += 1
        g["total_km"] += a["distance_km"] or 0.0
        g["total_time_s"] += a["moving_time_s"] or 0
        g["elev_gain_m"] += a["elev_gain_m"] or 0.0
    # arrondis
    for t, g in out.items():
        g["total_km"] = round(g["total_km"], 2)
        g["total_time_h"] = round(g["total_time_s"] / 3600.0, 2)
        g.pop("total_time_s", None)
        g["elev_gain_m"] = round(g["elev_gain_m"], 1)
    return out

def _fetch_streams(activity_id: int, token: str):
    # séries temporelles (cardio, vitesse) – attention aux quotas
    # nécessite en général scope `activity:read_all` pour activités privées
    url = f"{_API}/activities/{activity_id}/streams"
    params = {"keys": "heartrate,velocity_smooth", "key_by_type": "true"}
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
    if r.status_code != 200:
        return None
    js = r.json()
    # on renvoie uniquement ce qui est utile et pas trop volumineux
    out = {}
    if isinstance(js, dict):
        hr = js.get("heartrate", {}).get("data")
        sp = js.get("velocity_smooth", {}).get("data")
        out["heartrate"] = hr if isinstance(hr, list) else None
        out["velocity_smooth_mps"] = sp if isinstance(sp, list) else None
    return out

def get_weekly_summary(_token_from_query: str | None):
    token = _token_from_query or _get_access_token()
    if not token:
        return {"error": "no_access_token"}

    after = _since_monday_ts()
    url = f"{_API}/athlete/activities"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"after": after, "per_page": 100}, timeout=20)

    # token expiré → refresh & retry
    if r.status_code in (401, 403):
        token = _refresh_access_token()
        if not token:
            return {"error": "auth_failed", "detail": r.text}
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"after": after, "per_page": 100}, timeout=20)

    if r.status_code != 200:
        try:
            return {"error": "strava_api_error", "status_code": r.status_code, "detail": r.json()}
        except Exception:
            return {"error": "strava_api_error", "status_code": r.status_code, "detail": r.text}

    data = r.json()
    # filtrer triathlon core
    acts_fmt = [_fmt_activity(a) for a in data if (a.get("type") in ("Ride", "Run", "Swim"))]

    # résumé global
    total_km = round(sum(a["distance_km"] or 0 for a in acts_fmt), 2)
    total_time_h = round(sum(a["moving_time_s"] or 0 for a in acts_fmt) / 3600.0, 2)

    return {
        "summary": {"total_km": total_km, "total_time_h": total_time_h, "activities": len(acts_fmt)},
        "by_sport": _group_by_sport(acts_fmt),
        "activities": acts_fmt,
    }

def get_weekly_details(_token_from_query: str | None, with_streams: bool = False):
    """Identique à summary mais ajoute (optionnel) les streams FC/vitesse par activité."""
    base = get_weekly_summary(_token_from_query)
    if not isinstance(base, dict) or "activities" not in base:
        return base  # erreur propagée

    if with_streams:
        token = _get_access_token()
        for a in base["activities"]:
            s = _fetch_streams(a["id"], token)
            a["streams"] = s  # peut être None si indispo

    return base
