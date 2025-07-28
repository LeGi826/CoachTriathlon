import requests
from datetime import datetime, timedelta

def get_weekly_summary(access_token):
    today = datetime.now()
    last_monday = today - timedelta(days=today.weekday())
    after = int(last_monday.timestamp())

    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"after": after, "per_page": 100}

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    total_distance = 0
    total_duration = 0
    count = 0

    for activity in data:
        if activity["type"] in ["Ride", "Run", "Swim"]:
            total_distance += activity["distance"]
            total_duration += activity["moving_time"]
            count += 1

    return {
        "total_km": round(total_distance / 1000, 1),
        "total_time_h": round(total_duration / 3600, 2),
        "rides": count
    }
