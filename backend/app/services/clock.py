"""
Household-local dates.

Every "this month" and "today" in the product is a household judgement, not a
UTC one. A household in America/Phoenix rolls into a new month seven hours
after UTC does, and using UTC meant the dashboard could show an empty new
month all evening on the last day of the old one.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FALLBACK_TIMEZONE = "America/Phoenix"


def household_zone(name: str | None) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name or FALLBACK_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        try:
            return ZoneInfo(FALLBACK_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError):
            # No tz database at all: UTC is wrong but predictable.
            return timezone.utc


def today_in(name: str | None) -> date:
    """Today as the household experiences it."""
    return datetime.now(household_zone(name)).date()


def month_start_in(name: str | None) -> date:
    return today_in(name).replace(day=1)
