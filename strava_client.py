import requests
from datetime import datetime, timedelta, timezone

STRAVA_API = "https://www.strava.com/api/v3"

# Groupes pratiques
TRI_TYPES = {"Swim", "Ride", "Run"}
ENDURANCE_EXTRA = {"Walk", "Hike", "VirtualRide", "Workout", "Rowing", "Elliptical"}
# NB: on ne limite rien si 'all' (allowed = None)

def resolve_types(types_param: str) -> set[str] | None:
    """
    'tri' -> Swim/Ride/Run
    'endurance' -> TRI + quelques séances cardio génériques
    'all' -> None => aucun filtre (on prend tout, y compris WeightTraining/Yoga/etc.)
    CSV -> set explicite, ex: "Ride,Run,Swim,Workout,WeightTraining"
    """
    t = (types_param or "").strip().lower()
    if t in ("", "tri"):
        return set(TRI_TYPES)
    if t == "endurance":
        return set(TRI_TYPES | ENDURANCE_EXTRA)
    if t == "all":
        return None
    # CSV personnalisé
    custom = {x.strip() for x in types_param.split(",") if x.strip()}
    return custom or set(TRI_TYPES)


def _monday_utc_midnight_ts() -> int:
    """
    Lundi 00:00:00 UTC de la semaine courante — évite d'exclure un lundi soir par erreur.
    """
    now_utc = datetime.now(timezone.utc)
    monday_utc = (now_utc - timedelta(days=now_utc.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(monday_utc.timestamp())


def _fetch_week_activities(access_token: str, after_ts: int) -> list[dict]:
    """
    Récupère les activités depuis lundi 00:00 UTC. Paginer si besoin.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    activities: list[dict] = []
    page = 1
    per_page = 100

    while True:
        resp = requests.get(
            f"{STRAVA_API}/athlete/activities",
            headers=headers,
            params={"after": after_ts, "per_page": per_page, "page": page},
            timeout=20,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < per_page:
            break
        page += 1

    return activities


def _fetch_streams(access_token: str, activity_id: int, keys=("heartrate", "velocity_smooth")) -> dict:
    """
    Essaie de récupérer les streams FC et vitesse lissée si dispo.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(
            f"{STRAVA_API}/activities/{activity_id}/streams",
            headers=headers,
            params={"keys": ",".join(keys), "key_by_type": True},
            timeout=20,
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
        # Formate en simple dict {key: [valeurs]}
        out = {}
        for k in keys:
            stream = data.get(k)
            if isinstance(stream, dict) and "data" in stream:
                out[k] = stream["data"]
        return out
    except requests.RequestException:
        return {}


def _safe_float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _safe_int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _format_activity(a: dict) -> dict:
    distance_km = _safe_float(a.get("distance"), 0.0) / 1000.0
    moving_s = _safe_int(a.get("moving_time"), 0)
    elapsed_s = _safe_int(a.get("elapsed_time"), 0)
    elev_gain = _safe_float(a.get("total_elevation_gain"), 0.0)
    avg_hr = _safe_float(a.get("average_heartrate"))
    max_hr = _safe_float(a.get("max_heartrate"))
    avg_speed_kmh = None
    max_speed_kmh = None
    if moving_s > 0:
        avg_speed_kmh = (distance_km / (moving_s / 3600.0)) if distance_km > 0 else None
    if a.get("max_speed") is not None:
        max_speed_kmh = _safe_float(a.get("max_speed")) * 3.6

    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "type": a.get("type"),
        "start_date_local": a.get("start_date_local"),
        "distance_km": round(distance_km, 2) if distance_km else 0.0,
        "moving_time_s": moving_s,
        "elapsed_time_s": elapsed_s,
        "elev_gain_m": round(elev_gain, 1) if elev_gain else 0.0,
        "avg_speed_kmh": round(avg_speed_kmh, 1) if avg_speed_kmh else None,
        "max_speed_kmh": round(max_speed_kmh, 1) if max_speed_kmh else None,
        "avg_heartrate": round(avg_hr, 1) if avg_hr is not None else None,
        "max_heartrate": round(max_hr, 1) if max_hr is not None else None,
        "suffer_score": _safe_float(a.get("suffer_score")),
        "trainer": bool(a.get("trainer")),
        "commute": bool(a.get("commute")),
    }


def _aggregate_by_sport(activities: list[dict]) -> dict:
    """
    Cumule par type d’activité.
    - distance_km : somme des distances (0 pour muscu/yoga…)
    - total_time_h : basé sur moving_time_s
    - avg_hr : moyenne simple des FC moyennes disponibles
    - max_hr : max des FC max observées
    """
    by = {}
    for a in activities:
        t = a["type"]
        g = by.setdefault(
            t,
            {
                "count": 0,
                "total_km": 0.0,
                "elev_gain_m": 0.0,
                "total_time_s": 0,
                "avg_hr_sum": 0.0,
                "avg_hr_n": 0,
                "max_hr": None,
            },
        )
        g["count"] += 1
        g["total_km"] += a.get("distance_km") or 0.0
        g["elev_gain_m"] += a.get("elev_gain_m") or 0.0
        g["total_time_s"] += a.get("moving_time_s") or 0

        avg_hr = a.get("avg_heartrate")
        max_hr = a.get("max_heartrate")
        if isinstance(avg_hr, (int, float)):
            g["avg_hr_sum"] += avg_hr
            g["avg_hr_n"] += 1
        if isinstance(max_hr, (int, float)):
            g["max_hr"] = max(max_hr, g["max_hr"] or max_hr)

    # format final
    out = {}
    for t, g in by.items():
        avg_hr = round(g["avg_hr_sum"] / g["avg_hr_n"], 1) if g["avg_hr_n"] else None
        out[t] = {
            "count": g["count"],
            "total_km": round(g["total_km"], 2),
            "elev_gain_m": round(g["elev_gain_m"], 1),
            "max_hr": g["max_hr"],
            "total_time_h": round(g["total_time_s"] / 3600.0, 2),
            "avg_hr": avg_hr,
        }
    return out


def get_weekly_details(access_token: str, allowed_types: set[str] | None, with_streams: bool = False) -> dict:
    after = _monday_utc_midnight_ts()
    raw = _fetch_week_activities(access_token, after)

    # Filtre par type si nécessaire
    filtered = []
    for a in raw:
        t = a.get("type")
        if allowed_types is None or t in allowed_types:
            filtered.append(_format_activity(a))

    # Ajout des streams si demandé (et si supportés)
    if with_streams:
        for a in filtered:
            streams = _fetch_streams(access_token, a["id"])
            if streams:
                a["streams"] = streams

    # Résumé global
    total_km = sum(a.get("distance_km") or 0.0 for a in filtered)
    total_time_s = sum(a.get("moving_time_s") or 0 for a in filtered)

    return {
        "summary": {
            "total_km": round(total_km, 2),
            "total_time_h": round(total_time_s / 3600.0, 2),
            "activities": len(filtered),
        },
        "by_sport": _aggregate_by_sport(filtered),
        "activities": filtered,
    }


def get_weekly_summary(access_token: str, allowed_types: set[str] | None) -> dict:
    """
    Version courte : total_km, total_time_h, nb sessions, et comptage par type.
    """
    details = get_weekly_details(access_token, allowed_types, with_streams=False)
    counts_by_type = {
        k: v["count"] for k, v in details["by_sport"].items()
    }
    return {
        "total_km": details["summary"]["total_km"],
        "total_time_h": details["summary"]["total_time_h"],
        "sessions": details["summary"]["activities"],
        "counts_by_type": counts_by_type,
    }
