"""Swiss business day calendar for the ALM pipeline.

Provides ``is_business_day()`` and ``next_business_day()`` with Swiss public
holidays hard-coded through 2030 (Easter-derived dates via algorithm).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache


def _easter(year: int) -> date:
    """Compute Easter Sunday for *year* using the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=16)
def swiss_holidays(year: int) -> set[date]:
    """Return the set of Swiss national + Zurich public holidays for *year*.

    Covers the holidays commonly observed by banks in Zurich:
    - New Year's Day (Jan 1)
    - Berchtoldstag (Jan 2)
    - Good Friday (Easter - 2)
    - Easter Monday (Easter + 1)
    - Labour Day (May 1)
    - Ascension Day (Easter + 39)
    - Whit Monday (Easter + 50)
    - Swiss National Day (Aug 1)
    - Christmas Day (Dec 25)
    - St. Stephen's Day (Dec 26)
    """
    e = _easter(year)
    return {
        date(year, 1, 1),     # New Year
        date(year, 1, 2),     # Berchtoldstag
        e - timedelta(days=2),  # Good Friday
        e + timedelta(days=1),  # Easter Monday
        date(year, 5, 1),     # Labour Day
        e + timedelta(days=39),  # Ascension
        e + timedelta(days=50),  # Whit Monday
        date(year, 8, 1),     # National Day
        date(year, 12, 25),   # Christmas
        date(year, 12, 26),   # St. Stephen's
    }


def is_business_day(d: date | datetime) -> bool:
    """Return True if *d* is a Swiss banking business day."""
    if isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in swiss_holidays(d.year)


def next_business_day(d: date | datetime) -> date:
    """Return the next business day on or after *d*."""
    if isinstance(d, datetime):
        d = d.date()
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def prev_business_day(d: date | datetime) -> date:
    """Return the most recent business day on or before *d*."""
    if isinstance(d, datetime):
        d = d.date()
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d
