import requests
from datetime import datetime, timedelta

def get_weekly_summary(access_token: str):
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday())
    after = int(last_monday.timestamp())

    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"after": after, "per_page": 100}

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    if resp.status_code != 200:
        # Retour clair si token expiré/invalid (401/403) ou autre
        try:
            detail = resp.json()
        except Exception:
            detail = {"text": resp.text}
        return {
            "error": "strava_api_error",
            "status_code": resp.status_code,
            "detail": detail
        }

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
