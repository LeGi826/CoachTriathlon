import os
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple

import requests

STRAVA_BASE = "https://www.strava.com/api/v3"

# -----------------------------
# Helpers Auth & Dates
# -----------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _week_start_end(today: datetime) -> Tuple[int, int]:
    """
    Retourne (after_ts, before_ts) en secondes epoch pour la semaine courante (du lundi 00:00:00 au dimanche 23:59:59).
    """
    # today en local => on reste simple: base UTC mais logique relative
    # On part du lundi de la semaine du "today"
    local_today = today.astimezone()  # convertit en TZ locale
    start_of_week = (local_today - timedelta(days=local_today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end_of_week = start_of_week + timedelta(days=7) - timedelta(seconds=1)
    return int(start_of_week.timestamp()), int(end_of_week.timestamp())

def _refresh_access_token_if_needed() -> str | None:
    """
    Si l'app utilise un flow 'server' (client_id/secret/refresh_token en env),
    régénère un access_token utilisable côté serveur. Sinon None.
    """
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        return None

    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if token:
        os.environ["ACCESS_TOKEN"] = token  # on le place en mémoire de process
    return token


def _auth_headers(access_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


# -----------------------------
# Fetch Activities + Streams
# -----------------------------

DEFAULT_TYPES = {
    "Ride",
    "Run",
    "Swim",
    "VirtualRide",
    "VirtualRun",
    "Hike",
    "Walk",
    "WeightTraining",   # musculation
    "Workout",          # renfo/PPG, circuits
    "Rowing",
    "Canoeing",
    "EBikeRide",
    "GravelRide",
    "Crossfit",
    "Yoga",
    "Elliptical",
    "AlpineSki",
    "NordicSki",
    "Snowboard",
    "InlineSkate",
}

def _parse_types_param(types: str) -> set[str]:
    if types.lower().strip() == "all":
        return DEFAULT_TYPES
    parts = [t.strip() for t in types.split(",") if t.strip()]
    return set(parts) if parts else DEFAULT_TYPES


def _fetch_week_activities(access_token: str, types: set[str]) -> List[Dict[str, Any]]:
    after_ts, before_ts = _week_start_end(_utc_now())
    activities: List[Dict[str, Any]] = []
    page = 1
    per_page = 100

    while True:
        r = requests.get(
            f"{STRAVA_BASE}/athlete/activities",
            headers=_auth_headers(access_token),
            params={"after": after_ts, "before": before_ts, "page": page, "per_page": per_page},
            timeout=30,
        )
        if r.status_code == 401:
            # Essai automatique de refresh si conf server présente
            new_token = _refresh_access_token_if_needed()
            if new_token:
                access_token = new_token
                # retry
                r = requests.get(
                    f"{STRAVA_BASE}/athlete/activities",
                    headers=_auth_headers(access_token),
                    params={"after": after_ts, "before": before_ts, "page": page, "per_page": per_page},
                    timeout=30,
                )
        r.raise_for_status()
        chunk = r.json()
        if not chunk:
            break
        # filtrage par type demandé
        for a in chunk:
            if a.get("type") in types:
                activities.append(a)
        if len(chunk) < per_page:
            break
        page += 1

    return activities


def _fetch_streams(access_token: str, activity_id: int, stream_keys: List[str]) -> Dict[str, List[float]]:
    """
    Récupère certains streams; Strava requiert 'keys=...' et 'key_by_type=true'.
    Renvoie ex: {"heartrate":[...], "velocity_smooth":[...]}
    """
    if not stream_keys:
        return {}
    r = requests.get(
        f"{STRAVA_BASE}/activities/{activity_id}/streams",
        headers=_auth_headers(access_token),
        params={"keys": ",".join(stream_keys), "key_by_type": "true"},
        timeout=30,
    )
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json() or {}
    out: Dict[str, List[float]] = {}
    # Le payload Strava pour key_by_type=true ressemble à {"heartrate":{"data":[...]}, ...}
    for k in stream_keys:
        v = data.get(k)
        if isinstance(v, dict) and isinstance(v.get("data"), list):
            out[k] = v["data"]
    return out


# -----------------------------
# Mappings & Safe getters
# -----------------------------

def _safe(a: Dict[str, Any], key: str, default=None):
    v = a.get(key, default)
    return v if v is not None else default


def _activity_to_brief(a: Dict[str, Any]) -> Dict[str, Any]:
    dist_km = float(_safe(a, "distance", 0.0)) / 1000.0
    moving = int(_safe(a, "moving_time", 0))
    elapsed = int(_safe(a, "elapsed_time", moving))
    elev = float(_safe(a, "total_elevation_gain", 0.0))
    type_ = _safe(a, "type", "Other")
    # vitesses (m/s -> km/h)
    avg_speed_kmh = None
    max_speed_kmh = None
    if _safe(a, "average_speed") is not None:
        avg_speed_kmh = float(a["average_speed"]) * 3.6
    if _safe(a, "max_speed") is not None:
        max_speed_kmh = float(a["max_speed"]) * 3.6

    return {
        "id": _safe(a, "id"),
        "name": _safe(a, "name"),
        "type": type_,
        "start_date_local": _safe(a, "start_date_local"),
        "distance_km": round(dist_km, 2),
        "moving_time_s": moving,
        "elapsed_time_s": elapsed,
        "elev_gain_m": round(elev, 1),
        "avg_speed_kmh": round(avg_speed_kmh, 1) if avg_speed_kmh is not None else None,
        "max_speed_kmh": round(max_speed_kmh, 1) if max_speed_kmh is not None else None,
        "avg_heartrate": _safe(a, "average_heartrate"),
        "max_heartrate": _safe(a, "max_heartrate"),
        "suffer_score": _safe(a, "suffer_score"),
        "trainer": bool(_safe(a, "trainer", False)),
        "commute": bool(_safe(a, "commute", False)),
    }


# -----------------------------
# Public: weekly summary/details
# -----------------------------

def get_weekly_summary(access_token: str, types: str = "all") -> Dict[str, Any]:
    type_set = _parse_types_param(types)
    acts = _fetch_week_activities(access_token, type_set)

    total_km = 0.0
    total_time = 0
    counts: Dict[str, int] = {}

    for a in acts:
        total_km += float(_safe(a, "distance", 0.0)) / 1000.0
        total_time += int(_safe(a, "moving_time", 0))
        t = _safe(a, "type", "Other")
        counts[t] = counts.get(t, 0) + 1

    return {
        "total_km": round(total_km, 2),
        "total_time_h": round(total_time / 3600.0, 2),
        "sessions": len(acts),
        "counts_by_type": counts,
    }


def get_weekly_details(access_token: str, types: str = "all", with_streams: bool = False) -> Dict[str, Any]:
    type_set = _parse_types_param(types)
    acts = _fetch_week_activities(access_token, type_set)

    details: List[Dict[str, Any]] = []
    by_sport: Dict[str, Dict[str, Any]] = {}
    sum_km = 0.0
    sum_time = 0

    for a in acts:
        brief = _activity_to_brief(a)
        if with_streams:
            streams = _fetch_streams(access_token, brief["id"], ["heartrate", "velocity_smooth"])
            if streams:
                # pour rester lisible en JSON
                brief["streams"] = {
                    "heartrate": streams.get("heartrate"),
                    "velocity_smooth_mps": streams.get("velocity_smooth"),
                }
        details.append(brief)

        # agrégation par sport
        sp = brief["type"]
        g = by_sport.setdefault(
            sp,
            {"count": 0, "total_km": 0.0, "elev_gain_m": 0.0, "total_time_s": 0, "avg_hr_sum": 0.0, "avg_hr_n": 0, "max_hr": None},
        )
        g["count"] += 1
        g["total_km"] += brief["distance_km"]
        g["elev_gain_m"] += brief["elev_gain_m"]
        g["total_time_s"] += int(brief["moving_time_s"])
        if brief.get("avg_heartrate") is not None:
            g["avg_hr_sum"] += float(brief["avg_heartrate"])
            g["avg_hr_n"] += 1
        if brief.get("max_heartrate") is not None:
            g["max_hr"] = max(g["max_hr"] or 0, float(brief["max_heartrate"]))

        sum_km += brief["distance_km"]
        sum_time += int(brief["moving_time_s"])

    # finalize by_sport
    for sp, g in by_sport.items():
        g["total_km"] = round(g["total_km"], 2)
        g["elev_gain_m"] = round(g["elev_gain_m"], 1)
        g["total_time_h"] = round(g["total_time_s"] / 3600.0, 2)
        if g["avg_hr_n"] > 0:
            g["avg_hr"] = round(g["avg_hr_sum"] / g["avg_hr_n"], 1)
        else:
            g["avg_hr"] = None
        if g["max_hr"] is None:
            g["max_hr"] = None
        del g["avg_hr_sum"], g["avg_hr_n"], g["total_time_s"]

    return {
        "summary": {"total_km": round(sum_km, 2), "total_time_h": round(sum_time / 3600.0, 2), "activities": len(acts)},
        "by_sport": by_sport,
        "activities": details,
    }


# -----------------------------
# Cardio Analysis (zones + TRIMP)
# -----------------------------

def _estimate_hrmax(activities: List[Dict[str, Any]]) -> int | None:
    """
    Essai d'estimation HRmax: max des max_heartrate connus sur la semaine.
    Si aucun, retourne None.
    """
    mx = None
    for a in activities:
        v = _safe(a, "max_heartrate")
        if v is not None:
            v = float(v)
            mx = v if mx is None else max(mx, v)
    if mx is None:
        return None
    # on arrondit au bpm
    return int(round(mx))


def _zones_percent_max(hrmax: int) -> List[Tuple[str, int, int]]:
    """
    Zones = %HRmax (bornes inclusives inf, exclusive sup sauf Z5).
    Z1: <60%, Z2: 60-70, Z3: 70-80, Z4: 80-90, Z5: >=90
    Retourne une liste [(zone_label, min_bpm, max_bpm_inclus)] où max=None pour la dernière.
    """
    z = []
    z.append(("Z1", 0, math.floor(0.60 * hrmax)))                # <60%
    z.append(("Z2", math.floor(0.60 * hrmax), math.floor(0.70 * hrmax)))
    z.append(("Z3", math.floor(0.70 * hrmax), math.floor(0.80 * hrmax)))
    z.append(("Z4", math.floor(0.80 * hrmax), math.floor(0.90 * hrmax)))
    z.append(("Z5", math.floor(0.90 * hrmax), None))             # >=90%
    return z

def _zones_karvonen(hrmax: int, hrrest: int = 60) -> List[Tuple[str, int, int]]:
    """
    Zones Karvonen (par défaut HRrest=60 si on ne la connaît pas) :
    On utilise % de réserve cardiaque: HRr = HRrest + p*(HRmax-HRrest)
    Bornes comme ci-dessus 60/70/80/90 %
    """
    def bpm(p: float) -> int:
        return int(round(hrrest + p * (hrmax - hrrest)))

    z = []
    z.append(("Z1", 0, bpm(0.60)))
    z.append(("Z2", bpm(0.60), bpm(0.70)))
    z.append(("Z3", bpm(0.70), bpm(0.80)))
    z.append(("Z4", bpm(0.80), bpm(0.90)))
    z.append(("Z5", bpm(0.90), None))
    return z


def _zone_index(bpm: int, zones: List[Tuple[str, int, int]]) -> int:
    for i, (_, lo, hi) in enumerate(zones):
        if hi is None:
            if bpm >= lo:
                return i
        else:
            if lo <= bpm < hi:
                return i
    return 0


def _trimp_banister(duration_s: int, avg_hr: float, hrmax: int) -> float:
    """
    TRIMP (Banister, version simple, unisexe ici):
    HRr = avg_hr / HRmax
    TRIMP = dur_min * HRr * 0.64 * exp(1.92 * HRr)
    """
    if duration_s <= 0 or not avg_hr or not hrmax:
        return 0.0
    hr_r = max(0.0, min(1.2, avg_hr / hrmax))  # clamp un peu
    dur_min = duration_s / 60.0
    return float(dur_min * hr_r * 0.64 * math.exp(1.92 * hr_r))


def _time_in_zones_from_streams(hr_stream: List[int], zones: List[Tuple[str, int, int]], sampling_s: int | None = None) -> Dict[str, int]:
    """
    Approxime le temps passé dans chaque zone à partir d'un stream HR (1 point ~ 1s si échantillonné chaque seconde).
    sampling_s: si connu, le pas d’échantillonnage (sinon 1s).
    Retourne un dict { "Z1": secondes, ... }
    """
    if not hr_stream:
        return {z[0]: 0 for z in zones}
    step = sampling_s or 1
    counts = [0] * len(zones)
    for bpm in hr_stream:
        if bpm is None:
            continue
        idx = _zone_index(int(bpm), zones)
        counts[idx] += step
    return {zones[i][0]: counts[i] for i in range(len(zones))}


def _time_in_zones_from_avg(avg_hr: float | None, duration_s: int, zones: List[Tuple[str, int, int]]) -> Dict[str, int]:
    """
    Si pas de stream HR, on met toute la durée dans la zone où se situe la moyenne.
    """
    out = {z[0]: 0 for z in zones}
    if not avg_hr or duration_s <= 0:
        return out
    idx = _zone_index(int(round(avg_hr)), zones)
    out[zones[idx][0]] = duration_s
    return out


def get_weekly_analysis(
    access_token: str,
    types: str = "all",
    with_streams: bool = True,
    zone_model: str = "percent_max",
    hrmax: int | None = None,
    lthr: int | None = None,   # réservé pour futurs modèles
) -> Dict[str, Any]:
    type_set = _parse_types_param(types)
    acts_raw = _fetch_week_activities(access_token, type_set)

    # Construire fiches détaillées (et récupérer streams si demandé)
    activities: List[Dict[str, Any]] = []
    for a in acts_raw:
        brief = _activity_to_brief(a)
        if with_streams:
            streams = _fetch_streams(access_token, brief["id"], ["heartrate", "velocity_smooth"])
            if streams:
                brief["streams"] = {
                    "heartrate": streams.get("heartrate"),
                    "velocity_smooth_mps": streams.get("velocity_smooth"),
                }
        activities.append(brief)

    # Estimation HRmax si non fourni
    use_hrmax = hrmax or _estimate_hrmax(activities)
    zones = _zones_percent_max(use_hrmax) if (use_hrmax and zone_model == "percent_max") else None

    # Si modèle Karvonen et HRmax ok, zones sur base Karvonen (HRrest inconnu → 60 bpm par défaut)
    if use_hrmax and zone_model == "karvonen":
        zones = _zones_karvonen(use_hrmax, hrrest=60)

    # Si toujours None (pas de HRmax trouvée), fallback sur HRmax=190 pour ne pas planter
    if zones is None:
        use_hrmax = 190
        zones = _zones_percent_max(use_hrmax)

    # Analyse par séance
    zone_labels = [z[0] for z in zones]
    weekly_zone_seconds = {z: 0 for z in zone_labels}
    weekly_trimp = 0.0
    total_time_s = 0

    analyzed_sessions: List[Dict[str, Any]] = []

    for b in activities:
        duration = int(b.get("moving_time_s") or 0)
        avg_hr = b.get("avg_heartrate")
        hr_stream = None
        if with_streams and isinstance(b.get("streams"), dict):
            hr_stream = b["streams"].get("heartrate")

        # Temps en zones
        if hr_stream and len(hr_stream) >= max(10, duration // 6):  # heuristique: stream crédible
            tiz = _time_in_zones_from_streams(hr_stream, zones, sampling_s=None)
        else:
            tiz = _time_in_zones_from_avg(avg_hr, duration, zones)

        # TRIMP
        trimp = _trimp_banister(duration, float(avg_hr) if avg_hr else 0.0, use_hrmax)

        # Agg weekly
        for z in zone_labels:
            weekly_zone_seconds[z] += int(tiz.get(z, 0))
        weekly_trimp += trimp
        total_time_s += duration

        analyzed_sessions.append({
            **b,
            "time_in_zones_s": tiz,
            "trimp": round(trimp, 1),
        })

    weekly_summary = {
        "sessions": len(analyzed_sessions),
        "total_time_h": round(total_time_s / 3600.0, 2),
        "trimp_total": round(weekly_trimp, 1),
        "time_in_zones_s": weekly_zone_seconds,
        "zone_model": zone_model,
        "hrmax_used": use_hrmax,
    }

    # Agrégats par type en reprenant TRIMP et temps en zone
    by_type: Dict[str, Dict[str, Any]] = {}
    for s in analyzed_sessions:
        t = s.get("type", "Other")
        bt = by_type.setdefault(
            t,
            {
                "count": 0,
                "total_time_s": 0,
                "trimp": 0.0,
                "time_in_zones_s": {z: 0 for z in zone_labels},
            },
        )
        bt["count"] += 1
        bt["total_time_s"] += int(s.get("moving_time_s") or 0)
        bt["trimp"] += float(s.get("trimp") or 0.0)
        for z in zone_labels:
            bt["time_in_zones_s"][z] += int(s["time_in_zones_s"].get(z, 0))

    # formatage heures/arrondis
    for t, bt in by_type.items():
        bt["total_time_h"] = round(bt["total_time_s"] / 3600.0, 2)
        bt["trimp"] = round(bt["trimp"], 1)
        del bt["total_time_s"]

    return {
        "weekly_summary": weekly_summary,
        "by_type": by_type,
        "sessions": analyzed_sessions,
        "zones_definition": [
            {"zone": z[0], "min_bpm": z[1], "max_bpm": z[2]} for z in zones
        ],
    }
