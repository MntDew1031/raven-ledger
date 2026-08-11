from datetime import date, datetime, timezone
from unittest.mock import patch

from app.services.clock import household_zone, month_start_in, today_in


def test_household_local_date_differs_from_utc_in_the_evening():
    """
    Regression: at 00:30 UTC on the 1st it is still 17:30 on the last day of
    the previous month in Phoenix. Using UTC made the dashboard flip to an
    empty new month hours early.
    """
    utc_moment = datetime(2026, 8, 1, 0, 30, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_moment.astimezone(tz) if tz else utc_moment

    with patch("app.services.clock.datetime", FrozenDatetime):
        assert today_in("America/Phoenix") == date(2026, 7, 31)
        assert month_start_in("America/Phoenix") == date(2026, 7, 1)
        assert today_in("UTC") == date(2026, 8, 1)


def test_unknown_timezone_falls_back_without_raising():
    assert household_zone("Not/AZone") is not None
    assert isinstance(today_in("Not/AZone"), date)
    assert isinstance(today_in(None), date)


def test_timezone_database_is_available():
    """zoneinfo needs a tz database; slim images lack one without tzdata."""
    from zoneinfo import ZoneInfo

    assert ZoneInfo("America/Phoenix") is not None
