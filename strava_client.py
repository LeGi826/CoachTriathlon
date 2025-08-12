import os
import requests
from datetime import datetime, timedelta

# Base API
_API = "https://www.strava.com/api/v3"

# --- Helpers OAuth ---------------------------------------------------------

def _refresh_access_token():
    """
    Rafraîchit l'access_token via STRAVA_CLIENT_ID/SECRET + STRAVA_REFRESH_TOKEN.
    Met à jour STRAVA_REFRESH_TOKEN en RAM si Strava en renvoie un nouveau.
    Retourne le nouvel access_token (str) ou None si échec.
    """
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
    except requests.RequestException as e:
        return None

    if resp.status_code != 200:
        return None

    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token")

    # Met à jour le refresh token en mémoire (RAM du process)
    if new_refresh:
        os.environ["STRAVA_REFRESH_TOKEN"] = new_refresh

    return new_access

def _get_access_token(maybe_from_query: str | None):
    """
    Priorité :
      1) token passé en query (si fourni)
      2) ACCESS_TOKEN (si présent)
      3) refresh automatique via refresh_token
    """
    if maybe_from_query:
        return maybe_from_query
    env_token = os.getenv("ACCESS_TOKEN")
    if env_token:
        return env_token
    return _refresh_access_token()

# --- Période (depuis lundi) -----------------------------------------------

def _since_monday_ts() -> int:
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday())
    return int(last_monday.timestamp())

# --- Formatage activité ----------------------------------------------------

def _fmt_activity(a: dict) -> dict:
    """
    Normalise les champs utiles d'une activité Strava en unités "humaines".
    """
    dist_km = float(a.get("distance", 0.0)) / 1000.0
    mov_s = int(a.get("moving_time", 0))
    elev = float(a.get("total_elevation_gain", 0.0) or 0.0)
    avg_spd = a.get("average_speed")   # m/s (si présent)
    max_spd = a.get("max_speed")       # m/s (si présent)

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
        "suffer_score": a.get("suffer_score"),  # suivant équipement/abonnement
        "trainer": a.get("trainer"),
        "commute": a.get("commute"),
    }

# --- Agrégats par sport (incl. cardio) ------------------------------------

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
        g["total_time_s"] += int(a.get("moving_time_s") or 0)
        g["elev_gain_m"] += float(a.get("elev_gain_m") or 0.0)

        avg_hr = a.get("avg_heartrate")
        max_hr = a.get("max_heartrate")
        if avg_hr is not None:
            try:
                g["sum_avg_hr"] += float(avg_hr)
                g["with_hr_count"] += 1
            except Exception:
                pass
        if max_hr is not None:
            try:
                g["max_hr"] = max(g["max_hr"], float(max_hr))
            except Exception:
                pass

    # Finalisation (arrondis + calculs dérivés)
    for sport, g in out.items():
        g["total_km"] = round(g["total_km"], 2)
        g["total_time_h"] = round(g["total_time_s"] / 3600.0, 2)
        g["elev_gain_m"] = round(g["elev_gain_m"], 1)
        g["avg_hr"] = round(g["sum_avg_hr"] / g["with_hr_count"], 1) if g["with_hr_count"] else None
        g["max_hr"] = g["max_hr"] or None
        # nettoyage interne
        g.pop("total_time_s", None)
        g.pop("sum_avg_hr", None)
        g.pop("with_hr_count", None)

    return out

# --- Streams (séries FC/vitesse) optionnels -------------------------------

def _fetch_streams(activity_id: int, token: str):
    """
    Récupère les séries temporelles (heartrate, velocity_smooth) si disponibles.
    Peut nécessiter le scope `activity:read_all` pour activités privées.
    """
    url = f"{_API}/activities/{activity_id}/streams"
    params = {"keys": "heartrate,velocity_smooth", "key_by_type": "true"}
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    js = r.json()
    out = {}
    if isinstance(js, dict):
        hr = js.get("heartrate", {}).get("data")
        sp = js.get("velocity_smooth", {}).get("data")
        out["heartrate"] = hr if isinstance(hr, list) else None
        out["velocity_smooth_mps"] = sp if isinstance(sp, list) else None
    return out

# --- Endpoints logiques appelés par FastAPI --------------------------------

def get_weekly_summary(token_from_query: str | None):
    """
    Retourne un résumé hebdo simple :
      { total_km, total_time_h, rides }
    """
    token = _get_access_token(token_from_query)
    if not token:
        return {"error": "no_access_token", "hint": "Configure STRAVA_* env vars or pass ?access_token="}

    after = _since_monday_ts()
    url = f"{_API}/athlete/activities"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"after": after, "per_page": 100}, timeout=20)
    except requests.RequestException as e:
        return {"error": "network_error", "detail": str(e)}

    # Token expiré → refresh & retry 1 fois
    if r.status_code in (401, 403):
        token = _refresh_access_token()
        if not token:
            return {"error": "auth_failed", "status_code": r.status_code, "detail": r.text}
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"after": after, "per_page": 100}, timeout=20)
        except requests.RequestException as e:
            return {"error": "network_error", "detail": str(e)}

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = {"text": r.text}
        return {"error": "strava_api_error", "status_code": r.status_code, "detail": detail}

    data = r.json()
    acts_fmt = [_fmt_activity(a) for a in data if (a.get("type") in ("Ride", "Run", "Swim"))]

    total_km = round(sum(a["distance_km"] or 0 for a in acts_fmt), 2)
    total_time_h = round(sum(a["moving_time_s"] or 0 for a in acts_fmt) / 3600.0, 2)

    return {
        "total_km": total_km,
        "total_time_h": total_time_h,
        "rides": len(acts_fmt),
    }

def get_weekly_details(token_from_query: str | None, with_streams: bool = False):
    """
    Retourne :
      - summary: total_km, total_time_h, activities
      - by_sport: agrégats par sport (incl. avg_hr, max_hr)
      - activities: liste détaillée d'activités
      - (optionnel) streams FC/vitesse par activité si with_streams=True
    """
    token = _get_access_token(token_from_query)
    if not token:
        return {"error": "no_access_token", "hint": "Configure STRAVA_* env vars or pass ?access_token="}

    after = _since_monday_ts()
    url = f"{_API}/athlete/activities"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"after": after, "per_page": 100}, timeout=20)
    except requests.RequestException as e:
        return {"error": "network_error", "detail": str(e)}

    # Token expiré → refresh & retry 1 fois
    if r.status_code in (401, 403):
        token = _refresh_access_token()
        if not token:
            return {"error": "auth_failed", "status_code": r.status_code, "detail": r.text}
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params={"after": after, "per_page": 100}, timeout=20)
        except requests.RequestException as e:
            return {"error": "network_error", "detail": str(e)}

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = {"text": r.text}
        return {"error": "strava_api_error", "status_code": r.status_code, "detail": detail}

    data = r.json()
    acts_fmt = [_fmt_activity(a) for a in data if (a.get("type") in ("Ride", "Run", "Swim"))]

    summary = {
        "total_km": round(sum(a["distance_km"] or 0 for a in acts_fmt), 2),
        "total_time_h": round(sum(a["moving_time_s"] or 0 for a in acts_fmt) / 3600.0, 2),
        "activities": len(acts_fmt),
    }
    by_sport = _group_by_sport(acts_fmt)

    # Streams optionnels
    if with_streams and acts_fmt:
        for a in acts_fmt:
            try:
                streams = _fetch_streams(int(a["id"]), token)
            except Exception:
                streams = None
            a["streams"] = streams

    return {
        "summary": summary,
        "by_sport": by_sport,
        "activities": acts_fmt,
    }
