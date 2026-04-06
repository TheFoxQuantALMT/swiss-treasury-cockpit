"""Tests for cockpit.calendar — Swiss business day calendar."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from cockpit.calendar import (
    _easter,
    is_business_day,
    next_business_day,
    prev_business_day,
    swiss_holidays,
)


class TestEaster:
    def test_known_dates(self):
        assert _easter(2025) == date(2025, 4, 20)
        assert _easter(2026) == date(2026, 4, 5)
        assert _easter(2027) == date(2027, 3, 28)


class TestSwissHolidays:
    def test_2026_count(self):
        h = swiss_holidays(2026)
        assert len(h) == 10

    def test_fixed_holidays(self):
        h = swiss_holidays(2026)
        assert date(2026, 1, 1) in h   # New Year
        assert date(2026, 1, 2) in h   # Berchtoldstag
        assert date(2026, 5, 1) in h   # Labour Day
        assert date(2026, 8, 1) in h   # National Day
        assert date(2026, 12, 25) in h  # Christmas
        assert date(2026, 12, 26) in h  # St. Stephen

    def test_easter_derived_2026(self):
        # Easter 2026 = April 5
        h = swiss_holidays(2026)
        assert date(2026, 4, 3) in h   # Good Friday (Easter - 2)
        assert date(2026, 4, 6) in h   # Easter Monday (Easter + 1)
        assert date(2026, 5, 14) in h  # Ascension (Easter + 39)
        assert date(2026, 5, 25) in h  # Whit Monday (Easter + 50)


class TestIsBusinessDay:
    def test_weekday(self):
        assert is_business_day(date(2026, 4, 7))  # Tuesday

    def test_saturday(self):
        assert not is_business_day(date(2026, 4, 4))  # Saturday

    def test_sunday(self):
        assert not is_business_day(date(2026, 4, 5))  # Sunday (also Easter)

    def test_holiday(self):
        assert not is_business_day(date(2026, 1, 1))  # New Year

    def test_good_friday(self):
        assert not is_business_day(date(2026, 4, 3))

    def test_accepts_datetime(self):
        assert is_business_day(datetime(2026, 4, 7, 12, 0))


class TestNextBusinessDay:
    def test_already_business_day(self):
        assert next_business_day(date(2026, 4, 7)) == date(2026, 4, 7)

    def test_saturday(self):
        assert next_business_day(date(2026, 4, 4)) == date(2026, 4, 7)

    def test_good_friday_weekend(self):
        # Good Friday April 3 → Easter Monday April 6 is holiday → Tuesday April 7
        assert next_business_day(date(2026, 4, 3)) == date(2026, 4, 7)


class TestPrevBusinessDay:
    def test_already_business_day(self):
        assert prev_business_day(date(2026, 4, 7)) == date(2026, 4, 7)

    def test_sunday(self):
        assert prev_business_day(date(2026, 4, 5)) == date(2026, 4, 2)

    def test_easter_monday(self):
        # Easter Monday April 6 → back to Thursday April 2 (Good Friday is holiday)
        assert prev_business_day(date(2026, 4, 6)) == date(2026, 4, 2)
