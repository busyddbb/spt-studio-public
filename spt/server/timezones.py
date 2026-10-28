"""America/Los_Angeles, with or without a time zone database.

macOS ships the IANA database, so ZoneInfo is used there as before. Python on
Windows has none unless the `tzdata` package is installed; ZoneInfo then raises,
and US Pacific time is computed from the current US rules instead (since 2007:
daylight time from the second Sunday of March 2:00 to the first Sunday of
November 2:00). Folds and gaps follow PEP 495 like ZoneInfo.
"""
from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PACIFIC_NAME = "America/Los_Angeles"
HOUR = dt.timedelta(hours=1)
ZERO = dt.timedelta(0)


def nth_sunday(year: int, month: int, n: int) -> dt.datetime:
    first = dt.datetime(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


class USPacific(dt.tzinfo):
    """US Pacific time from the post-2007 rules (no database needed)."""

    STANDARD = dt.timedelta(hours=-8)

    @staticmethod
    def bounds(year: int) -> tuple[dt.datetime, dt.datetime]:
        """Wall-clock start (2:00 PST) and end (2:00 PDT) of daylight time."""
        return nth_sunday(year, 3, 2) + 2 * HOUR, nth_sunday(year, 11, 1) + 2 * HOUR

    def dst(self, value: dt.datetime | None) -> dt.timedelta:
        if value is None:
            return ZERO
        start, end = self.bounds(value.year)
        wall = value.replace(tzinfo=None)
        if start + HOUR <= wall < end - HOUR:
            return HOUR
        if start <= wall < start + HOUR:          # 2:00–3:00 in March does not exist
            return HOUR if value.fold else ZERO
        if end - HOUR <= wall < end:              # 1:00–2:00 in November happens twice
            return ZERO if value.fold else HOUR
        return ZERO

    def utcoffset(self, value: dt.datetime | None) -> dt.timedelta:
        return self.STANDARD + self.dst(value)

    def tzname(self, value: dt.datetime | None) -> str:
        return "PDT" if self.dst(value) else "PST"

    def fromutc(self, value: dt.datetime) -> dt.datetime:
        utc = value.replace(tzinfo=None)
        start, end = self.bounds(utc.year)
        start_utc, end_utc = start - self.STANDARD, end - self.STANDARD - HOUR
        if start_utc <= utc < end_utc:
            return (utc + self.STANDARD + HOUR).replace(tzinfo=self, fold=0)
        fold = 1 if end_utc <= utc < end_utc + HOUR else 0   # the repeated hour, second time
        return (utc + self.STANDARD).replace(tzinfo=self, fold=fold)

    def __repr__(self) -> str:
        return "USPacific()"


def pacific() -> dt.tzinfo:
    try:
        return ZoneInfo(PACIFIC_NAME)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return USPacific()
