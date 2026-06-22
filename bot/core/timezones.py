import re
from datetime import timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TIMEZONE_ALIASES = {
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "eastern": "America/New_York",
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "central": "America/Chicago",
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "mountain": "America/Denver",
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    "ist": "Asia/Kolkata",
    "gmt": "UTC",
    "utc": "UTC",
}

UTC_OFFSET = re.compile(r"^utc\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)


def resolve_timezone(name):
    normalized = name.strip()
    alias = TIMEZONE_ALIASES.get(normalized.casefold())
    if alias:
        return ZoneInfo(alias)

    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        pass

    match = UTC_OFFSET.match(normalized)
    if not match:
        return None

    sign, hours, minutes = match.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
    if sign == "-":
        delta = -delta

    return timezone(delta, name=normalized.upper().replace(" ", ""))

