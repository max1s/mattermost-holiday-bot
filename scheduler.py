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
import public_holidays

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


def _fmt_reminder_range(start: date, end: date, sp: str = "full", ep: str = "full") -> str:
    """Day-prefixed range, with partial-day markers on the boundary days when set."""
    if start == end:
        if sp == "full":
            return _fmt_date_with_day(start)
        return f"{_fmt_date_with_day(start)} ({sp})"
    s = _fmt_date_with_day(start) + (f" ({sp})" if sp != "full" else "")
    e = _fmt_date_with_day(end)   + (f" ({ep})" if ep != "full" else "")
    return f"{s} -- {e}"


def _format_days(days_off: float) -> str:
    """Render a (possibly half) day count as '1 day' / '3 days' / '2.5 days'."""
    if days_off == int(days_off):
        n = int(days_off)
        return f"{n} day" if n == 1 else f"{n} days"
    return f"{days_off} days"


def _duration_days(start: date, end: date, sp: str, ep: str) -> float:
    n = (end - start).days + 1
    return n - 0.5 * (sp == "afternoon") - 0.5 * (ep == "morning")


def _row_part(row, key: str) -> str:
    try:
        v = row[key]
    except (IndexError, KeyError):
        return "full"
    return v or "full"


def _holiday_message(
    name: str, timing: str, start: date, end: date, label: str | None,
    *, effective_start: date | None = None, duration_suffix: str = "",
    start_part: str = "full", end_part: str = "full",
) -> str:
    """Build a single holiday announcement line, with partial-day markers."""
    clean = (label or "").strip().strip('"')
    suffix = f" — {clean}" if clean else ""

    # Same-day half-day: keep the legacy "**half day** (am|pm)" phrasing,
    # and drop the redundant part suffix from the date range itself.
    if start == end and start_part != "full":
        return (
            f"{name}: off **{timing}** for a **half day** "
            f"({start_part}) ({_fmt_reminder_range(start, end)}){suffix}"
        )

    dur_start = effective_start if effective_start is not None else start
    days_off = _duration_days(dur_start, end, start_part, end_part)
    duration = _format_days(days_off) + duration_suffix
    return (
        f"{name}: off **{timing}** for **{duration}** "
        f"({_fmt_reminder_range(start, end, start_part, end_part)}){suffix}"
    )


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
        # Drop holidays whose end_date has already passed — they overlap "this
        # week" by date arithmetic but aren't relevant to a forward-looking
        # summary (and would yield negative durations on the in-progress branch).
        hols_this  = [r for r in database.get_holidays_overlapping_range(this_mon, this_sun)
                      if date.fromisoformat(r["end_date"]) >= today]
        this_ids   = {row["id"] for row in hols_this}
        hols_next  = [r for r in database.get_holidays_overlapping_range(next_mon, next_sun)
                      if r["id"] not in this_ids]

        public_this = public_holidays.in_range(this_mon, this_sun)
        public_next = public_holidays.in_range(next_mon, next_sun)

        if not any([bdays_this, bdays_next, hols_this, hols_next, public_this, public_next]):
            logger.info("Weekly summary: nothing to report.")
            return

        aliases = database.get_all_aliases()

        def _name(row) -> str:
            alias = aliases.get(row["user_id"])
            if alias:
                return f"@{alias}"
            current = mattermost.get_username(row["user_id"])
            return f"@{current or row['username']}"

        for row in hols_this:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            if start < today:
                timing = "this week"
                effective_start = today
                duration_suffix = " more"
            else:
                timing = "this week"
                effective_start = None
                duration_suffix = ""
            mattermost.post_to_announcement_channel(
                _holiday_message(
                    _name(row), timing, start, end, row["label"],
                    effective_start=effective_start, duration_suffix=duration_suffix,
                    start_part=_row_part(row, "start_part"),
                    end_part=_row_part(row, "end_part"),
                )
            )

        for row in hols_next:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            mattermost.post_to_announcement_channel(
                _holiday_message(
                    _name(row), "next week", start, end, row["label"],
                    start_part=_row_part(row, "start_part"),
                    end_part=_row_part(row, "end_part"),
                )
            )

        if public_this:
            lines = [":flags: **Public holidays this week:**"]
            for d, label, flag, name in public_this:
                lines.append(f"- {flag} {label}: {_fmt_date_with_day(d)} — {name}")
            mattermost.post_to_announcement_channel("\n".join(lines))

        if public_next:
            lines = [":flags: **Public holidays next week:**"]
            for d, label, flag, name in public_next:
                lines.append(f"- {flag} {label}: {_fmt_date_with_day(d)} — {name}")
            mattermost.post_to_announcement_channel("\n".join(lines))

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
    Skipped on Mondays — the weekly summary already covers those holidays.
    """
    try:
        today    = _today()
        if today.weekday() == 0:  # Monday
            logger.debug("Daily reminders: skipping on Monday (covered by weekly summary).")
            return
        target_7 = today + timedelta(days=7)
        target_1 = today + timedelta(days=1)

        hols_7 = database.get_holidays_starting_on(target_7)
        hols_1 = database.get_holidays_starting_on(target_1)

        if not hols_7 and not hols_1:
            logger.debug("Daily reminders: nothing to report for %s.", today)
            return

        aliases = database.get_all_aliases()

        def _name(row) -> str:
            alias = aliases.get(row["user_id"])
            if alias:
                return f"@{alias}"
            current = mattermost.get_username(row["user_id"])
            return f"@{current or row['username']}"

        for row in hols_7:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            mattermost.post_to_announcement_channel(
                _holiday_message(
                    _name(row), "in 1 week", start, end, row["label"],
                    start_part=_row_part(row, "start_part"),
                    end_part=_row_part(row, "end_part"),
                )
            )

        for row in hols_1:
            start = date.fromisoformat(row["start_date"])
            end   = date.fromisoformat(row["end_date"])
            mattermost.post_to_announcement_channel(
                _holiday_message(
                    _name(row), "tomorrow", start, end, row["label"],
                    start_part=_row_part(row, "start_part"),
                    end_part=_row_part(row, "end_part"),
                )
            )

        logger.info("Daily reminders posted (7-day: %d, 1-day: %d).", len(hols_7), len(hols_1))

    except Exception:
        logger.exception("Failed to post daily reminders.")
