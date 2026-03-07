from datetime import datetime
from zoneinfo import ZoneInfo

from django.db.models import F, Max, Q, Sum
from django.utils import timezone

STATE_TIMEZONES = {
    "AL": "America/Chicago",
    "AK": "America/Anchorage",
    "AZ": "America/Phoenix",
    "AR": "America/Chicago",
    "CA": "America/Los_Angeles",
    "CO": "America/Denver",
    "CT": "America/New_York",
    "DE": "America/New_York",
    "FL": "America/New_York",
    "GA": "America/New_York",
    "HI": "Pacific/Honolulu",
    "IA": "America/Chicago",
    "ID": "America/Boise",
    "IL": "America/Chicago",
    "IN": "America/New_York",
    "KS": "America/Chicago",
    "KY": "America/New_York",
    "LA": "America/Chicago",
    "MA": "America/New_York",
    "MD": "America/New_York",
    "ME": "America/New_York",
    "MI": "America/New_York",
    "MN": "America/Chicago",
    "MO": "America/Chicago",
    "MS": "America/Chicago",
    "MT": "America/Denver",
    "NC": "America/New_York",
    "ND": "America/Chicago",
    "NE": "America/Chicago",
    "NH": "America/New_York",
    "NJ": "America/New_York",
    "NM": "America/Denver",
    "NV": "America/Los_Angeles",
    "NY": "America/New_York",
    "OH": "America/New_York",
    "OK": "America/Chicago",
    "OR": "America/Los_Angeles",
    "PA": "America/New_York",
    "RI": "America/New_York",
    "SC": "America/New_York",
    "SD": "America/Chicago",
    "TN": "America/Chicago",
    "TX": "America/Chicago",
    "UT": "America/Denver",
    "VA": "America/New_York",
    "VT": "America/New_York",
    "WA": "America/Los_Angeles",
    "WI": "America/Chicago",
    "WV": "America/New_York",
    "WY": "America/Denver",
    "DC": "America/New_York",
}


def property_timezone(amenity):
    try:
        state_code = amenity.property.city.state.code.upper()
        tz_name = STATE_TIMEZONES.get(state_code)
        if tz_name:
            return ZoneInfo(tz_name)
    except Exception:
        pass
    return timezone.get_default_timezone()


def _local_now(amenity=None):
    tz = property_timezone(amenity) if amenity is not None else timezone.get_default_timezone()
    return timezone.now().astimezone(tz)


def calculate_amenity_status(amenity):
    """
    Compute occupancy status, capacity, and confidence for an amenity.
    Confidence is a heuristic based on active sessions and recency of activity.
    """
    active_sessions = amenity.sessions.filter(is_active=True)
    current_count = (
        active_sessions.annotate(headcount=F("guest_count") + 1).aggregate(total=Sum("headcount"))["total"] or 0
    )

    all_sessions = amenity.sessions.all()
    last_in = all_sessions.aggregate(last=Max("check_in_time"))["last"]
    last_out = all_sessions.aggregate(last=Max("check_out_time"))["last"]
    last_activity = max([dt for dt in [last_in, last_out] if dt], default=None)

    now_local = _local_now(amenity)
    now_time = now_local.time()
    if amenity.open_time <= amenity.close_time:
        within_hours = amenity.open_time <= now_time <= amenity.close_time
    else:
        within_hours = now_time >= amenity.open_time or now_time <= amenity.close_time

    is_open = amenity.is_active and within_hours

    capacity = amenity.capacity or 0
    if not is_open:
        status = "CLOSED"
    elif capacity and current_count >= capacity:
        status = "FULL"
    elif capacity and current_count >= 0.8 * capacity:
        status = "BUSY"
    else:
        status = "AVAILABLE"

    if last_activity is None:
        confidence = 20
    else:
        minutes_since = (now_local - last_activity).total_seconds() / 60
        base = 90 if current_count > 0 else 60
        confidence = max(10, min(99, int(base - minutes_since * 2)))

    return {
        "current_count": current_count,
        "capacity": capacity,
        "status": status,
        "confidence": confidence,
    }
