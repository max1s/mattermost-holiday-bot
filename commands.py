"""
commands.py — Business logic for all slash command handlers.

Each function receives parsed fields from the Mattermost slash command
POST body and returns a dict suitable for JSON response to Mattermost.

All responses are ephemeral (visible only to the invoking user) unless
noted otherwise.
"""

from datetime import date, datetime, timedelta

import config
import database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(text: str, response_type: str = "ephemeral") -> dict:
    """Build a Mattermost slash command response dict."""
    return {"response_type": response_type, "text": text}


def _today() -> date:
    """Current date in the configured timezone."""
    return datetime.now(tz=config.TIMEZONE).date()


def _parse_date(token: str) -> date | None:
    """Try to parse a YYYY-MM-DD string. Returns None on failure."""
    try:
        return datetime.strptime(token, "%Y-%m-%d").date()
    except ValueError:
        return None


def _fmt_date(d: date) -> str:
    """Format a date as 'Mon 1 Jun 2026'."""
    return d.strftime("%a %-d %b %Y")


def _fmt_date_range(start: date, end: date) -> str:
    """
    Format a date range compactly:
      same day  → 'Mon 1 Jun 2026'
      same year → 'Mon 1 Jun – Fri 5 Jun 2026'
      diff year → 'Mon 29 Dec 2025 – Fri 2 Jan 2026'
    """
    if start == end:
        return _fmt_date(start)
    if start.year == end.year:
        start_str = start.strftime("%a %-d %b")
        end_str = end.strftime("%a %-d %b %Y")
        return f"{start_str} – {end_str}"
    return f"{_fmt_date(start)} – {_fmt_date(end)}"


# ---------------------------------------------------------------------------
# /holiday-add <YYYY-MM-DD> [YYYY-MM-DD] [label]
# ---------------------------------------------------------------------------

_HOLIDAY_ADD_USAGE = (
    "Usage: `/holiday-add <YYYY-MM-DD> [YYYY-MM-DD] [label]`\n"
    "Examples:\n"
    "• `/holiday-add 2026-08-03` — single day off\n"
    "• `/holiday-add 2026-08-03 2026-08-07` — date range\n"
    "• `/holiday-add 2026-08-03 2026-08-07 Summer holiday` — with label"
)


def cmd_holiday_add(user_id: str, username: str, text: str) -> dict:
    if not text.strip():
        return _resp(_HOLIDAY_ADD_USAGE)

    # Split into at most 3 tokens: start, maybe-end-or-label-start, rest-of-label
    parts = text.strip().split(maxsplit=2)

    # Token 0: required start date
    start = _parse_date(parts[0])
    if start is None:
        return _resp(
            f":x: Could not parse `{parts[0]}` as a date (expected YYYY-MM-DD).\n\n"
            + _HOLIDAY_ADD_USAGE
        )

    end: date = start
    label: str | None = None

    if len(parts) >= 2:
        maybe_end = _parse_date(parts[1])
        if maybe_end is not None:
            # Token 1 is a valid date — use as end date
            end = maybe_end
            if len(parts) == 3:
                label = parts[2].strip() or None
        else:
            # Token 1 is not a date — treat "parts[1] [parts[2]]" as label
            label_parts = [parts[1]]
            if len(parts) == 3:
                label_parts.append(parts[2])
            label = " ".join(label_parts).strip() or None

    if end < start:
        return _resp(":x: End date cannot be before start date.")

    holiday_id = database.add_holiday(user_id, username, start.isoformat(), end.isoformat(), label)

    label_str = f": _{label}_" if label else ""
    return _resp(
        f":white_check_mark: Holiday added (ID: **{holiday_id}**)\n"
        f"_{_fmt_date_range(start, end)}{label_str}_"
    )


# ---------------------------------------------------------------------------
# /holiday-list
# ---------------------------------------------------------------------------

def cmd_holiday_list(user_id: str) -> dict:
    today = _today()
    rows = database.get_upcoming_holidays(user_id, today)

    if not rows:
        return _resp(":white_check_mark: You have no upcoming holidays registered.")

    lines = [":desert_island: **Your upcoming holidays:**\n"]
    lines.append("| ID | Dates | Label |")
    lines.append("|----|-------|-------|")
    for row in rows:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        label = row["label"] or ""
        lines.append(f"| {row['id']} | {_fmt_date_range(start, end)} | {label} |")

    lines.append("\nUse `/holiday-delete <ID>` to remove one.")
    return _resp("\n".join(lines))


# ---------------------------------------------------------------------------
# /holiday-delete <id>
# ---------------------------------------------------------------------------

def cmd_holiday_delete(user_id: str, text: str) -> dict:
    text = text.strip()
    if not text:
        return _resp("Usage: `/holiday-delete <ID>`\nFind IDs with `/holiday-list`.")

    try:
        holiday_id = int(text)
        if holiday_id <= 0:
            raise ValueError
    except ValueError:
        return _resp(f":x: `{text}` is not a valid holiday ID. IDs are positive integers.")

    deleted = database.delete_holiday(holiday_id, user_id)
    if not deleted:
        return _resp(f":x: No holiday with ID **{holiday_id}** found.")

    return _resp(f":white_check_mark: Holiday **{holiday_id}** deleted.")


# ---------------------------------------------------------------------------
# /birthday-set <YYYY-MM-DD>
# ---------------------------------------------------------------------------

def cmd_birthday_set(user_id: str, username: str, text: str) -> dict:
    text = text.strip()
    if not text:
        return _resp(
            "Usage: `/birthday-set <YYYY-MM-DD>`\n"
            "Example: `/birthday-set 1990-07-04`"
        )

    bday = _parse_date(text)
    if bday is None:
        return _resp(
            f":x: Could not parse `{text}` as a date (expected YYYY-MM-DD).\n"
            "Example: `/birthday-set 1990-07-04`"
        )

    was_update = database.set_birthday(user_id, username, bday.isoformat())
    action = "updated" if was_update else "set"
    display = bday.strftime("%-d %B")  # e.g. "4 July"

    return _resp(
        f":birthday: Birthday {action} to **{display}**.\n"
        "_The year is stored privately and never shown to others._"
    )


# ---------------------------------------------------------------------------
# /birthday-delete
# ---------------------------------------------------------------------------

def cmd_birthday_delete(user_id: str) -> dict:
    deleted = database.delete_birthday(user_id)
    if not deleted:
        return _resp(":white_check_mark: No birthday was set — nothing to delete.")
    return _resp(":white_check_mark: Your birthday has been removed.")


# ---------------------------------------------------------------------------
# /away-today
# ---------------------------------------------------------------------------

def cmd_away_today() -> dict:
    today = _today()
    rows = database.get_holidays_overlapping_date(today)

    if not rows:
        return _resp(
            f":white_check_mark: No one is away today ({_fmt_date(today)}).",
            response_type="in_channel",
        )

    lines = [f":desert_island: **Away today ({_fmt_date(today)}):**\n"]
    for row in rows:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        label_str = f" _({row['label']})_" if row["label"] else ""
        lines.append(f"- @{row['username']}: {_fmt_date_range(start, end)}{label_str}")

    return _resp("\n".join(lines), response_type="in_channel")
