import os
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple, Optional

import requests

STRAVA_BASE = "https://www.strava.com/api/v3"

# -----------------------------
# Helpers Auth & Dates
# -----------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _week_start_end(today: datetime) -> Tuple[int, int]:
    local_today = today.astimezone()
    start_of_week = (local_today - timedelta(days=local_today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end_of_week = start_of_week + timedelta(days=7) - timedelta(seconds=1)
    return int(start_of_week.timestamp()), int(end_of_week.timestamp())

def _refresh_access_token_if_needed() -> Optional[str]:
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
        os.environ["ACCESS_TOKEN"] = token
    return token

def _auth_headers(access_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}

# -----------------------------
# Streams helpers
# -----------------------------

def _downsample(seq: Optional[List[float]], max_points: int) -> Optional[List[float]]:
    if not seq:
        return seq
    n = len(seq)
    if n <= max_points:
        return seq
    step = max(1, n // max_points)
    return seq[::step][:max_points]

# -----------------------------
# Fetch Activities + Streams
# -----------------------------

DEFAULT_TYPES = {
    "Ride", "Run", "Swim", "VirtualRide", "VirtualRun",
    "Hike", "Walk", "WeightTraining", "Workout",
    "Rowing", "Canoeing", "EBikeRide", "GravelRide",
    "Crossfit", "Yoga", "Elliptical",
    "AlpineSki", "NordicSki", "Snowboard", "InlineSkate",
}

def _parse_types_param(types: str) -> set[str]:
    if types.lower().strip() == "all":
        return DEFAULT_TYPES
    parts = [t.strip() for t in types.split(",") if t.strip()]
    return set(parts) if parts else DEFAULT_TYPES

def _fetch_week_activities(access_token: str, types: set[str]) -> List[Dict[str, Any]]:
    after_ts, before_ts = _week_start_end(_utc_now())
    activities: List[Dict[str, Any]] = []
    page, per_page = 1, 100
    while True:
        r = requests.get(
            f"{STRAVA_BASE}/athlete/activities",
            headers=_auth_headers(access_token),
            params={"after": after_ts, "before": before_ts, "page": page, "per_page": per_page},
            timeout=30,
        )
        if r.status_code == 401:
            new_token = _refresh_access_token_if_needed()
            if new_token:
                access_token = new_token
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
        for a in chunk:
            if a.get("type") in types:
                activities.append(a)
        if len(chunk) < per_page:
            break
        page += 1
    return activities

def _fetch_streams(access_token: str, activity_id: int, stream_keys: List[str]) -> Dict[str, List[float]]:
    if not stream_keys:
        return {}
    r = requests.get(
        f"{STRAVA_BASE}/activities/{activity_id}/streams",
        headers=_auth_headers(access_token),
        params={"keys": ",".join(stream_keys), "key_by_type": "true"},
        timeout=30,
    )
    if r.status_code == 401:
        new_token = _refresh_access_token_if_needed()
        if new_token:
            access_token = new_token
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
    avg_speed_kmh = float(a["average_speed"]) * 3.6 if _safe(a, "average_speed") is not None else None
    max_speed_kmh = float(a["max_speed"]) * 3.6 if _safe(a, "max_speed") is not None else None
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
# Zones / TRIMP / Decoupling
# -----------------------------

def _estimate_hrmax(activities: List[Dict[str, Any]]) -> Optional[int]:
    mx: Optional[float] = None
    for a in activities:
        v = _safe(a, "max_heartrate")
        if v is not None:
            v = float(v)
            mx = v if mx is None else max(mx, v)
    if mx is None:
        return None
    return int(round(mx))

def _zones_percent_max(hrmax: int):
    return [
        ("Z1", 0, math.floor(0.60 * hrmax)),
        ("Z2", math.floor(0.60 * hrmax), math.floor(0.70 * hrmax)),
        ("Z3", math.floor(0.70 * hrmax), math.floor(0.80 * hrmax)),
        ("Z4", math.floor(0.80 * hrmax), math.floor(0.90 * hrmax)),
        ("Z5", math.floor(0.90 * hrmax), None),
    ]

def _zones_karvonen(hrmax: int, hrrest: int = 60):
    def bpm(p: float) -> int:
        return int(round(hrrest + p * (hrmax - hrrest)))
    return [
        ("Z1", 0, bpm(0.60)),
        ("Z2", bpm(0.60), bpm(0.70)),
        ("Z3", bpm(0.70), bpm(0.80)),
        ("Z4", bpm(0.80), bpm(0.90)),
        ("Z5", bpm(0.90), None),
    ]

def _zone_index(bpm: int, zones) -> int:
    for i, (_, lo, hi) in enumerate(zones):
        if hi is None and bpm >= lo:
            return i
        if hi is not None and lo <= bpm < hi:
            return i
    return 0

def _trimp_banister(duration_s: int, avg_hr: float, hrmax: int) -> float:
    if duration_s <= 0 or not avg_hr or not hrmax:
        return 0.0
    hr_r = max(0.0, min(1.2, avg_hr / hrmax))
    dur_min = duration_s / 60.0
    return float(dur_min * hr_r * 0.64 * math.exp(1.92 * hr_r))

def _time_in_zones_from_streams(hr_stream: List[int], zones, sampling_s: Optional[int] = None) -> Dict[str, int]:
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

def _time_in_zones_from_avg(avg_hr: Optional[float], duration_s: int, zones) -> Dict[str, int]:
    out = {z[0]: 0 for z in zones}
    if not avg_hr or duration_s <= 0:
        return out
    idx = _zone_index(int(round(avg_hr)), zones)
    out[zones[idx][0]] = duration_s
    return out

def _hr_decoupling(hr: List[float], vel_mps: List[float]) -> Optional[float]:
    n = min(len(hr), len(vel_mps))
    if n < 60:
        return None
    mid = n // 2
    def avg_ratio(vv, hh):
        pairs = [(vv[i], hh[i]) for i in range(len(vv)) if hh[i] and hh[i] > 0]
        if not pairs:
            return None
        ratios = [p[0] / p[1] for p in pairs]
        return sum(ratios) / len(ratios)
    r1 = avg_ratio(vel_mps[:mid], hr[:mid])
    r2 = avg_ratio(vel_mps[mid:], hr[mid:])
    if r1 is None or r2 is None or r1 == 0:
        return None
    return float(round((r2 - r1) / r1 * 100.0, 2))

# -----------------------------
# Public: weekly summary/details
# -----------------------------

def get_weekly_summary(access_token: str, types: str = "all") -> Dict[str, Any]:
    type_set = _parse_types_param(types)
    acts = _fetch_week_activities(access_token, type_set)
    total_km, total_time = 0.0, 0
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

def get_weekly_details(
    access_token: str,
    types: str = "all",
    streams_mode: str = "none",      # 'none' | 'summary' | 'full'
    max_points: int = 1500,
    compute_decoupling: bool = False,
    hrmax: Optional[int] = None,
    hrrest: Optional[int] = None,
) -> Dict[str, Any]:
    type_set = _parse_types_param(types)
    acts = _fetch_week_activities(access_token, type_set)

    # zones pour temps en zones
    est_hrmax = hrmax or _estimate_hrmax([_activity_to_brief(a) for a in acts]) or 190
    zones = _zones_percent_max(est_hrmax)

    details: List[Dict[str, Any]] = []
    by_sport: Dict[str, Dict[str, Any]] = {}
    sum_km, sum_time = 0.0, 0

    include_streams = streams_mode in ("summary", "full")

    for a in acts:
        brief = _activity_to_brief(a)
        hr_stream = None
        vel_stream = None

        if include_streams:
            streams = _fetch_streams(access_token, int(brief["id"]), ["heartrate", "velocity_smooth"])
            if streams:
                hr_stream = streams.get("heartrate")
                vel_stream = streams.get("velocity_smooth")
                # Pour 'full' seulement, on renvoie les tableaux (downsample)
                if streams_mode == "full":
                    brief["streams"] = {
                        "heartrate": _downsample(hr_stream, max_points) if hr_stream else None,
                        "velocity_smooth_mps": _downsample(vel_stream, max_points) if vel_stream else None,
                    }

        # Temps en zones (avec streams si dispo et crédibles)
        duration = int(brief.get("moving_time_s") or 0)
        avg_hr = brief.get("avg_heartrate")
        if hr_stream and len(hr_stream) >= max(10, duration // 6):
            tiz = _time_in_zones_from_streams(hr_stream, zones, sampling_s=None)
        else:
            tiz = _time_in_zones_from_avg(avg_hr, duration, zones)
        brief["time_in_zones_s"] = tiz

        # Découpling si demandé et streams dispo (Run/Ride)
        if compute_decoupling and hr_stream and vel_stream and (brief.get("type") in {"Ride", "VirtualRide", "Run", "TrailRun"}):
            brief["hr_decoupling_percent"] = _hr_decoupling(hr_stream, vel_stream)

        details.append(brief)

        # agrégations
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

    for sp, g in by_sport.items():
        g["total_km"] = round(g["total_km"], 2)
        g["elev_gain_m"] = round(g["elev_gain_m"], 1)
        g["total_time_h"] = round(g["total_time_s"] / 3600.0, 2)
        g["avg_hr"] = round(g["avg_hr_sum"] / g["avg_hr_n"], 1) if g["avg_hr_n"] > 0 else None
        g["max_hr"] = g["max_hr"] if g["max_hr"] is not None else None
        del g["avg_hr_sum"], g["avg_hr_n"], g["total_time_s"]

    return {
        "summary": {"total_km": round(sum_km, 2), "total_time_h": round(sum_time / 3600.0, 2), "activities": len(acts)},
        "by_sport": by_sport,
        "activities": details,
        "zones_definition": [{"zone": z[0], "min_bpm": z[1], "max_bpm": z[2]} for z in zones],
        "hrmax_used": est_hrmax,
        "streams_mode": streams_mode,
        "max_points": max_points if streams_mode == "full" else None,
    }

# -----------------------------
# Public: weekly analysis (compact)
# -----------------------------

def get_weekly_analysis(
    access_token: str,
    types: str = "all",
    with_streams: bool = True,
    zone_model: str = "percent_max",
    hrmax: Optional[int] = None,
    hrrest: Optional[int] = None,
    compute_decoupling: bool = True,
) -> Dict[str, Any]:
    type_set = _parse_types_param(types)
    acts_raw = _fetch_week_activities(access_token, type_set)

    activities: List[Dict[str, Any]] = []
    for a in acts_raw:
        brief = _activity_to_brief(a)
        hr_stream = vel_stream = None
        if with_streams:
            streams = _fetch_streams(access_token, int(brief["id"]), ["heartrate", "velocity_smooth"])
            if streams:
                hr_stream = streams.get("heartrate")
                vel_stream = streams.get("velocity_smooth")
        brief_streams = {"heartrate": hr_stream, "velocity_smooth_mps": vel_stream} if (hr_stream or vel_stream) else None
        if brief_streams:
            brief["streams"] = brief_streams
        activities.append(brief)

    use_hrmax = hrmax or _estimate_hrmax(activities) or 190
    zones = _zones_karvonen(use_hrmax, hrrest or 60) if zone_model == "karvonen" else _zones_percent_max(use_hrmax)

    zone_labels = [z[0] for z in zones]
    weekly_zone_seconds = {z: 0 for z in zone_labels}
    weekly_trimp = 0.0
    total_time_s = 0

    daily_trimp: Dict[str, float] = {}
    trimp_by_type: Dict[str, float] = {}
    analyzed_sessions: List[Dict[str, Any]] = []

    for b in activities:
        duration = int(b.get("moving_time_s") or 0)
        avg_hr = b.get("avg_heartrate")
        hr_stream = None
        vel_stream = None
        if isinstance(b.get("streams"), dict):
            hr_stream = b["streams"].get("heartrate")
            vel_stream = b["streams"].get("velocity_smooth_mps")

        if hr_stream and len(hr_stream) >= max(10, duration // 6):
            tiz = _time_in_zones_from_streams(hr_stream, zones, sampling_s=None)
        else:
            tiz = _time_in_zones_from_avg(avg_hr, duration, zones)

        trimp = _trimp_banister(duration, float(avg_hr) if avg_hr else 0.0, use_hrmax)

        dec = None
        if compute_decoupling and hr_stream and vel_stream and (b.get("type") in {"Ride", "VirtualRide", "Run", "TrailRun"}):
            dec = _hr_decoupling(hr_stream, vel_stream)

        for z in zone_labels:
            weekly_zone_seconds[z] += int(tiz.get(z, 0))
        weekly_trimp += trimp
        total_time_s += duration

        day_key = (b.get("start_date_local") or "")[:10] or "unknown"
        daily_trimp[day_key] = round(daily_trimp.get(day_key, 0.0) + trimp, 2)

        t = b.get("type", "Other")
        trimp_by_type[t] = round(trimp_by_type.get(t, 0.0) + trimp, 2)

        analyzed_sessions.append({
            **b,
            "time_in_zones_s": tiz,
            "trimp": round(trimp, 1),
            **({"hr_decoupling_percent": dec} if dec is not None else {}),
        })

    weekly_summary = {
        "sessions": len(analyzed_sessions),
        "total_time_h": round(total_time_s / 3600.0, 2),
        "trimp_total": round(weekly_trimp, 1),
        "time_in_zones_s": weekly_zone_seconds,
        "zone_model": zone_model,
        "hrmax_used": use_hrmax,
        "hrrest_used": hrrest,
    }

    monotony = None
    strain = None
    trimp_values = list(daily_trimp.values())
    if trimp_values:
        mean_daily = sum(trimp_values) / len(trimp_values)
        if len(trimp_values) > 1:
            var = sum((x - mean_daily) ** 2 for x in trimp_values) / (len(trimp_values) - 1)
            std = math.sqrt(var)
        else:
            std = 0.0
        monotony = round(mean_daily / (std if std > 0 else 1.0), 2)
        strain = round(weekly_summary["trimp_total"] * monotony, 2)

    recovery = {
        "daily_trimp": daily_trimp,
        "trimp_by_type": trimp_by_type,
        "monotony": monotony,
        "strain": strain,
        "notes": "TRIMP (Banister). Monotony/Strain (Foster). Décorrélation HR par séance si streams disponibles.",
    }

    by_type: Dict[str, Dict[str, Any]] = {}
    for s in analyzed_sessions:
        t = s.get("type", "Other")
        bt = by_type.setdefault(
            t,
            {"count": 0, "total_time_s": 0, "trimp": 0.0, "time_in_zones_s": {z: 0 for z in zone_labels}},
        )
        bt["count"] += 1
        bt["total_time_s"] += int(s.get("moving_time_s") or 0)
        bt["trimp"] += float(s.get("trimp") or 0.0)
        for z in zone_labels:
            bt["time_in_zones_s"][z] += int(s["time_in_zones_s"].get(z, 0))

    for t, bt in by_type.items():
        bt["total_time_h"] = round(bt["total_time_s"] / 3600.0, 2)
        bt["trimp"] = round(bt["trimp"], 1)
        del bt["total_time_s"]

    return {
        "weekly_summary": weekly_summary,
        "recovery": recovery,
        "by_type": by_type,
        "sessions": analyzed_sessions,   # pas de streams bruts downsamplés ici
        "zones_definition": [{"zone": z[0], "min_bpm": z[1], "max_bpm": z[2]} for z in zones],
    }

