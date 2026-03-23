"""
scheduler.py — APScheduler job functions for scheduled announcements.

Two jobs:
  1. job_weekly_summary()  — Monday 9AM: birthday + holiday summary
  2. job_daily_reminders() — Mon–Fri 9AM: one-week and one-day holiday reminders
"""

import logging
from datetime import date, datetime, timedelta

import config
import database
import mattermost

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _today() -> date:
    """Current date in the configured timezone."""
    return datetime.now(tz=config.TIMEZONE).date()


def _week_bounds(ref: date) -> tuple[date, date]:
    """Return (Monday, Sunday) of the ISO week containing ref."""
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _fmt_date(d: date) -> str:
    """Format a date using the configured DATE_FORMAT."""
    return d.strftime(config.DATE_FORMAT)


def _fmt_date_range(start: date, end: date) -> str:
    if start == end:
        return _fmt_date(start)
    return f"{_fmt_date(start)} – {_fmt_date(end)}"


def _fmt_date_with_day(d: date) -> str:
    return f"{d.strftime('%a')}, {_fmt_date(d)}"


def _fmt_reminder_range(start: date, end: date) -> str:
    if start == end:
        return _fmt_date_with_day(start)
    return f"{_fmt_date_with_day(start)} -- {_fmt_date_with_day(end)}"


def _fmt_birthday_date(birth_date_str: str) -> str:
    """Format a birthday as day + month name, e.g. '04 Jul'. Always human-readable."""
    bday = date.fromisoformat(birth_date_str)
    return bday.strftime("%d %b")


# ---------------------------------------------------------------------------
# Weekly summary (Monday 9AM)
# ---------------------------------------------------------------------------

def job_weekly_summary() -> None:
    """
    Post a weekly overview to the announcement channel every Monday.
    Covers birthdays and holidays for this week (Mon–Sun) and next week.
    """
    try:
        today = _today()
        this_mon, this_sun = _week_bounds(today)
        next_mon = this_mon + timedelta(weeks=1)
        next_sun = this_sun + timedelta(weeks=1)

        bdays_this = database.get_birthdays_in_range(this_mon, this_sun)
        bdays_next = database.get_birthdays_in_range(next_mon, next_sun)
        hols_this  = database.get_holidays_overlapping_range(this_mon, this_sun)
        this_ids   = {row["id"] for row in hols_this}
        hols_next  = [r for r in database.get_holidays_overlapping_range(next_mon, next_sun)
                      if r["id"] not in this_ids]

        if not any([bdays_this, bdays_next, hols_this, hols_next]):
            logger.info("Weekly summary: nothing to report.")
            return

        aliases = database.get_all_aliases()

        def _name(row) -> str:
            return f"@{aliases.get(row['user_id'], row['username'])}"

        def _duration(start: date, end: date) -> str:
            days = (end - start).days + 1
            return f"{days} day" if days == 1 else f"{days} days"


        for row in hols_this:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            mattermost.post_to_announcement_channel(
                f"{_name(row)}: off **this week** for **{_duration(start, end)}** ({_fmt_reminder_range(start, end)})"
            )

        for row in hols_next:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            mattermost.post_to_announcement_channel(
                f"{_name(row)}: off **next week** for **{_duration(start, end)}** ({_fmt_reminder_range(start, end)})"
            )

        logger.info("Weekly summary posted.")

    except Exception:
        logger.exception("Failed to post weekly summary.")


# ---------------------------------------------------------------------------
# Daily reminders (Mon–Fri 9AM)
# ---------------------------------------------------------------------------

def job_daily_reminders() -> None:
    """
    Post holiday reminders for holidays starting exactly 7 days or 1 day from today.
    One message per person, no grouped headers.
    """
    try:
        today    = _today()
        target_7 = today + timedelta(days=7)
        target_1 = today + timedelta(days=1)

        hols_7 = database.get_holidays_starting_on(target_7)
        hols_1 = database.get_holidays_starting_on(target_1)

        if not hols_7 and not hols_1:
            logger.debug("Daily reminders: nothing to report for %s.", today)
            return

        aliases = database.get_all_aliases()

        def _name(row) -> str:
            return f"@{aliases.get(row['user_id'], row['username'])}"

        def _duration(start: date, end: date) -> str:
            days = (end - start).days + 1
            return f"{days} day" if days == 1 else f"{days} days"


        for row in hols_7:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            mattermost.post_to_announcement_channel(
                f"{_name(row)}: off in **1 week** for **{_duration(start, end)}** ({_fmt_reminder_range(start, end)})"
            )

        for row in hols_1:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            mattermost.post_to_announcement_channel(
                f"{_name(row)}: off **tomorrow** for **{_duration(start, end)}** ({_fmt_reminder_range(start, end)})"
            )

        logger.info("Daily reminders posted (7-day: %d, 1-day: %d).", len(hols_7), len(hols_1))

    except Exception:
        logger.exception("Failed to post daily reminders.")
