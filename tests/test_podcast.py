from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta

import holidays

from podcast import TAIPEI, is_taiwan_workday, next_run_at_or_after


class TaiwanWorkdayTests(unittest.TestCase):
    def test_weekends_are_not_workdays(self) -> None:
        self.assertFalse(is_taiwan_workday(date(2026, 11, 21)))
        self.assertFalse(is_taiwan_workday(date(2026, 11, 22)))

    def test_weekday_public_holiday_is_not_a_workday(self) -> None:
        year_holidays = holidays.country_holidays("TW", years=[2026])
        holiday = next(day for day in year_holidays if day.weekday() < 5)
        self.assertFalse(is_taiwan_workday(holiday))

    def test_regular_weekday_is_a_workday(self) -> None:
        year_holidays = holidays.country_holidays("TW", years=[2026])
        day = date(2026, 1, 1)
        while day.weekday() >= 5 or day in year_holidays:
            day += timedelta(days=1)
        self.assertTrue(is_taiwan_workday(day))


class SchedulerTests(unittest.TestCase):
    def test_next_run_uses_taipei_time_and_six_am(self) -> None:
        now = datetime(2026, 11, 20, 5, 0, tzinfo=TAIPEI)
        next_run = next_run_at_or_after(now)
        self.assertEqual(next_run.time(), time(6, 0, tzinfo=TAIPEI))
        self.assertEqual(next_run.date(), now.date())

    def test_next_run_moves_to_future_on_or_after_six(self) -> None:
        now = datetime(2026, 11, 20, 6, 1, tzinfo=TAIPEI)
        next_run = next_run_at_or_after(now)
        self.assertGreaterEqual(next_run, now)
        self.assertEqual(next_run.hour, 6)
        self.assertEqual(next_run.minute, 0)

    def test_naive_datetime_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            next_run_at_or_after(datetime(2026, 11, 20, 5, 0))


if __name__ == "__main__":
    unittest.main()
