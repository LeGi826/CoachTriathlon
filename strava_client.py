import os
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# --- Constantes API ---
_API = "https://www.strava.com/api/v3"
_TRI_TYPES = {"Ride", "Run", "Swim"}


# ---------- Helpers OAuth ----------
def _refresh_access_token() -> Optional[str]:
    """
    Rafraîchit l'access_token via variables d'env :
      STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN
    Met à jour STRAVA_REFRESH_TOKEN en RAM si Strava en renvoie un nouveau.
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
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None

    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token")
    if new_refresh:
        os.environ["STRAVA_REFRESH_TOKEN"] = str(new_refresh)  # en RAM
    return new_access


def _get_access_token(maybe_from_query: Optional[str]) -> Optional[str]:
    """
    Priorité :
      1) token fourni en query
      2) ACCESS_TOKEN dans l'env (si tu l'as défini côté Render)
      3) refresh via STRAVA_REFRESH_TOKEN
    """
    if maybe_from_query:
        return maybe_from_query
    env_token = os.getenv("ACCESS_TOKEN")
    if env_token:
        return env_token
    return _refresh_access_token()


# ---------- Fenêtre (depuis lundi) ----------
def _since_monday_ts() -> int:
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday())
    return int(last_monday.timestamp())


# ---------- Paramètre 'types' ----------
def _parse_types(types_mode: str):
    """
    Retourne :
      - "all" si types_mode == "all"
      - _TRI_TYPES si types_mode vide ou "tri"
      - un set pour une liste personnalisée 'Type1,Type2,...'
    """
    if not types_mode or types_mode == "tri":
        return _TRI_TYPES
    if types_mode == "all":
        return "all"
    wanted = {t.strip() for t in types_mode.split(",") if t.strip()}
    return wanted or _TRI_TYPES


def _filter_acts(data: List[Dict[str, Any]], types_mode: str) -> List[Dict[str, Any]]:
    parsed = _parse_types(types_mode)
    if parsed == "all":
        return data[:]  # toutes les activités
    return [a for a in data if (a.get("type") in parsed)]


# ---------- Formatage d'une activité ----------
def _fmt_activity(a: Dict[str, Any]) -> Dict[str, Any]:
    dist_km = float(a.get("distance", 0.0)) / 1000.0
    mov_s = int(a.get("moving_time", 0))
    elev = float(a.get("total_elevation_gain", 0.0) or 0.0)
    avg_spd = a.get("average_speed")  # m/s
    max_spd = a.get("max_speed")      # m/s

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


# ---------- Agrégats ----------
def _group_by_sport(acts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}

    for a in acts:
        sport = a.get("type") or "Other"
        g = out.setdefault(
            sport,
            {
                "count": 0,
                "total_km": 0.0,
                "total_time_s": 0,
                "elev_gain_m": 0.0,
                # cardio agrégé
                "sum_avg_hr": 0.0,
                "with_hr_count": 0,
                "max_hr": 0.0,
            },
        )
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

    for sport, g in out.items():
        g["total_km"] = round(g["total_km"], 2)
        g["total_time_h"] = round(g["total_time_s"] / 3600.0, 2)
        g["elev_gain_m"] = round(g["elev_gain_m"], 1)
        g["avg_hr"] = (
            round(g["sum_avg_hr"] / g["with_hr_count"], 1) if g["with_hr_count"] else None
        )
        g["max_hr"] = g["max_hr"] or None
        # nettoyage interne
        g.pop("total_time_s", None)
        g.pop("sum_avg_hr", None)
        g.pop("with_hr_count", None)

    return out


def _counts_by_type(acts: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for a in acts:
        t = a.get("type") or "Other"
        counts[t] = counts.get(t, 0) + 1
    return counts


# ---------- Streams (FC/vitesse) ----------
def _fetch_streams(activity_id: int, token: str) -> Optional[Dict[str, Any]]:
    """
    Série temporelle (heartrate, velocity_smooth).
    Peut nécessiter le scope `activity:read_all` pour les activités privées.
    """
    url = f"{_API}/activities/{activity_id}/streams"
    params = {"keys": "heartrate,velocity_smooth", "key_by_type": "true"}
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        )
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    js = r.json()
    out: Dict[str, Any] = {}
    if isinstance(js, dict):
        hr = js.get("heartrate", {}).get("data")
        sp = js.get("velocity_smooth", {}).get("data")
        out["heartrate"] = hr if isinstance(hr, list) else None
        out["velocity_smooth_mps"] = sp if isinstance(sp, list) else None
    return out


# ---------- Récup semaine courante ----------
def _fetch_week_data(token: str, types: str):
    after = _since_monday_ts()
    url = f"{_API}/athlete/activities"

    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"after": after, "per_page": 100},
            timeout=20,
        )
    except requests.RequestException as e:
        return None, {"error": "network_error", "detail": str(e)}

    if r.status_code in (401, 403):
        token2 = _refresh_access_token()
        if not token2:
            return None, {"error": "auth_failed"}
        try:
            r = requests.get(
                url,
                headers={"Authorization": f"Bearer {token2}"},
                params={"after": after, "per_page": 100},
                timeout=20,
            )
        except requests.RequestException as e:
            return None, {"error": "network_error", "detail": str(e)}

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = {"text": r.text}
        return None, {"error": "strava_api_error", "status_code": r.status_code, "detail": detail}

    raw = r.json()
    filtered = _filter_acts(raw, types)
    acts_fmt = [_fmt_activity(a) for a in filtered]
    return acts_fmt, None


# ---------- Fonctions utilisées par FastAPI ----------
def get_weekly_summary(token_from_query: Optional[str], types: str = "tri"):
    token = _get_access_token(token_from_query)
    if not token:
        return {"error": "no_access_token", "hint": "Configure STRAVA_* env vars or pass ?access_token="}

    acts_fmt, err = _fetch_week_data(token, types)
    if err:
        return err

    total_km = round(sum(a.get("distance_km") or 0 for a in acts_fmt), 2)
    total_time_h = round(sum(a.get("moving_time_s") or 0 for a in acts_fmt) / 3600.0, 2)
    counts = _counts_by_type(acts_fmt)

    return {
        "total_km": total_km,
        "total_time_h": total_time_h,
        "sessions": len(acts_fmt),
        "counts_by_type": counts,
    }


def get_weekly_details(token_from_query: Optional[str], with_streams: bool = False, types: str = "tri"):
    token = _get_access_token(token_from_query)
    if not token:
        return {"error": "no_access_token", "hint": "Configure STRAVA_* env vars or pass ?access_token="}

    acts_fmt, err = _fetch_week_data(token, types)
    if err:
        return err

    summary = {
        "total_km": round(sum(a.get("distance_km") or 0 for a in acts_fmt), 2),
        "total_time_h": round(sum(a.get("moving_time_s") or 0 for a in acts_fmt) / 3600.0, 2),
        "activities": len(acts_fmt),
    }
    by_sport = _group_by_sport(acts_fmt)

    if with_streams and acts_fmt:
        token2 = _get_access_token(None)  # re-check/refresh si besoin
        for a in acts_fmt:
            try:
                streams = _fetch_streams(int(a["id"]), token2)
            except Exception:
                streams = None
            a["streams"] = streams

    return {
        "summary": summary,
        "by_sport": by_sport,
        "activities": acts_fmt,
    }
