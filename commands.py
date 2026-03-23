"""
commands.py — Business logic for all slash command handlers.

Each function receives parsed fields from the Mattermost slash command
POST body and returns a dict suitable for JSON response to Mattermost.

All responses are ephemeral (visible only to the invoking user) unless
noted otherwise.
"""

import logging
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
import database

logger = logging.getLogger(__name__)


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
    """Try to parse a date string using the configured DATE_FORMAT. Returns None on failure."""
    try:
        return datetime.strptime(token, config.DATE_FORMAT).date()
    except ValueError:
        return None


def _fmt_date(d: date) -> str:
    """Format a date using the configured DATE_FORMAT."""
    return d.strftime(config.DATE_FORMAT)


def _display_name(user_id: str, username: str) -> str:
    """Return the user's alias (with @) if set, otherwise @username."""
    alias = database.get_alias(user_id)
    return f"@{alias}" if alias else f"@{username}"


def _fmt_date_range(start: date, end: date) -> str:
    """Format a date range. Single date if start == end, otherwise 'start – end'."""
    if start == end:
        return _fmt_date(start)
    return f"{_fmt_date(start)} – {_fmt_date(end)}"


def _fmt_date_with_day(d: date) -> str:
    return f"{d.strftime('%a')}, {_fmt_date(d)}"


def _fmt_range_with_day(start: date, end: date) -> str:
    if start == end:
        return _fmt_date_with_day(start)
    return f"{_fmt_date_with_day(start)} -- {_fmt_date_with_day(end)}"


def _example(d: date) -> str:
    """Return a date formatted as an example for help/usage text."""
    return d.strftime(config.DATE_FORMAT)


# ---------------------------------------------------------------------------
# Help text (used by /holiday-help and the channel join welcome message)
# ---------------------------------------------------------------------------

def help_text() -> str:
    """Build the help message using the currently configured date format."""
    ex_single = _example(date(2026, 8, 3))
    ex_end    = _example(date(2026, 8, 7))
    ex_bday   = _example(date(1990, 7, 4))
    fmt       = config.DATE_FORMAT

    return (
        ":calendar: **Holiday Bot — Commands**\n\n"
        "**Holidays**\n"
        f"- `/holiday-add <{fmt}> [{fmt}] [label]` — Add a holiday (single day or range, label optional)\n"
        "- `/holiday-list` — List your upcoming holidays\n"
        "- `/holiday-list all` — List everyone's upcoming holidays\n"
        "- `/holiday-list @username` — List a specific person's upcoming holidays\n"
        "- `/holiday-delete <ID>` — Delete one of your holidays by ID\n\n"
        "**Birthdays**\n"
        f"- `/birthday-set <{fmt}>` — Set or update your birthday\n"
        "- `/birthday-delete` — Remove your birthday\n\n"
        "**Queries**\n"
        "- `/away-today` — See everyone who is away today (posts to channel)\n"
        "- `/holiday-help` — Show this help message\n\n"
        "**Settings**\n"
        "- `/holiday-user-rename <display-name>` — Set a display name alias for yourself\n\n"
        "**Experimental**\n"
        f"- `/holiday-notify <{fmt}> [{fmt}] [label]` — Add a holiday and notify the company administrator\n\n"
        "**Scheduled Announcements**\n"
        "- Monday 9AM — Weekly summary of birthdays and holidays for this week and next\n"
        "- Weekdays 9AM — Reminder when someone's holiday is 1 week or 1 day away\n\n"
        "**Examples**\n"
        f"```\n"
        f"/holiday-add {ex_single}\n"
        f"/holiday-add {ex_single} {ex_end}\n"
        f"/holiday-add {ex_single} {ex_end} Summer holiday\n"
        f"/birthday-set {ex_bday}\n"
        f"/away-today\n"
        "```"
    )


def cmd_help() -> dict:
    return _resp(help_text())


# ---------------------------------------------------------------------------
# Shared argument parser for /holiday-add and /holiday-notify
# ---------------------------------------------------------------------------

def _holiday_add_usage() -> str:
    fmt = config.DATE_FORMAT
    ex1 = _example(date(2026, 8, 3))
    ex2 = _example(date(2026, 8, 7))
    return (
        f"Usage: `/holiday-add <{fmt}> [{fmt}] [label]`\n"
        "Examples:\n"
        f"• `/holiday-add {ex1}` — single day off\n"
        f"• `/holiday-add {ex1} {ex2}` — date range\n"
        f"• `/holiday-add {ex1} {ex2} Summer holiday` — with label"
    )


def _parse_holiday_args(text: str) -> tuple[date, date, str | None] | str:
    """
    Parse the argument string for /holiday-add and /holiday-notify.
    Returns (start, end, label) on success, or an error/usage string on failure.
    """
    if not text.strip():
        return _holiday_add_usage()

    parts = text.strip().split(maxsplit=2)

    start = _parse_date(parts[0])
    if start is None:
        return (
            f":x: Could not parse `{parts[0]}` as a date "
            f"(expected format: `{config.DATE_FORMAT}`).\n\n"
            + _holiday_add_usage()
        )

    end: date = start
    label: str | None = None

    if len(parts) >= 2:
        maybe_end = _parse_date(parts[1])
        if maybe_end is not None:
            end = maybe_end
            if len(parts) == 3:
                label = parts[2].strip() or None
        else:
            label_parts = [parts[1]]
            if len(parts) == 3:
                label_parts.append(parts[2])
            label = " ".join(label_parts).strip() or None

    if end < start:
        return ":x: End date cannot be before start date."

    return start, end, label


# ---------------------------------------------------------------------------
# /holiday-add
# ---------------------------------------------------------------------------

def cmd_holiday_add(user_id: str, username: str, text: str) -> dict:
    parsed = _parse_holiday_args(text)
    if isinstance(parsed, str):
        return _resp(parsed)

    start, end, label = parsed
    holiday_id = database.add_holiday(user_id, username, start.isoformat(), end.isoformat(), label)
    label_str = f": _{label}_" if label else ""
    return _resp(
        f":white_check_mark: Holiday added (ID: **{holiday_id}**)\n"
        f"_{_fmt_date_range(start, end)}{label_str}_"
    )


# ---------------------------------------------------------------------------
# /holiday-list
# ---------------------------------------------------------------------------

def cmd_holiday_list(user_id: str, text: str) -> dict:
    today = _today()
    arg = text.strip().lstrip("@").lower()

    if not arg:
        rows = database.get_upcoming_holidays(user_id, today)
        if not rows:
            return _resp(":white_check_mark: You have no upcoming holidays registered.")
        lines = [":desert_island: **Your upcoming holidays:**\n"]
        for row in rows:
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row["end_date"])
            label_str = f" _({row['label']})_" if row["label"] else ""
            lines.append(f"- **{row['id']}** — {_fmt_range_with_day(start, end)}{label_str}")
        lines.append("\n_Use `/holiday-delete <ID>` to remove one._")
        return _resp("\n".join(lines))

    if arg == "all":
        rows = database.get_all_upcoming_holidays(today)
        if not rows:
            return _resp(":white_check_mark: No upcoming holidays registered.")
        lines = [":desert_island: **All upcoming holidays:**\n"]
        aliases = database.get_all_aliases()
        for row in rows:
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row["end_date"])
            label_str = f" _({row['label']})_" if row["label"] else ""
            name = f"@{aliases.get(row['user_id'], row['username'])}"
            lines.append(f"- {name}: {_fmt_range_with_day(start, end)}{label_str}")
        return _resp("\n".join(lines))

    # Specific name — try alias lookup first, fall back to username column
    target_user_id = database.get_user_id_by_name(arg)
    if target_user_id:
        rows = database.get_upcoming_holidays_by_user_id(target_user_id, today)
    else:
        rows = database.get_upcoming_holidays_by_username(arg, today)
    if not rows:
        return _resp(f":white_check_mark: No upcoming holidays found for {arg}.")
    display = database.get_alias(target_user_id) if target_user_id else arg
    lines = [f":desert_island: **Upcoming holidays for {display}:**\n"]
    for row in rows:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        label_str = f" _({row['label']})_" if row["label"] else ""
        lines.append(f"- {_fmt_range_with_day(start, end)}{label_str}")
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
# /birthday-set <date>
# ---------------------------------------------------------------------------

def cmd_birthday_set(user_id: str, username: str, text: str) -> dict:
    text = text.strip()
    if not text:
        return _resp(
            f"Usage: `/birthday-set <{config.DATE_FORMAT}>`\n"
            f"Example: `/birthday-set {_example(date(1990, 7, 4))}`"
        )

    bday = _parse_date(text)
    if bday is None:
        return _resp(
            f":x: Could not parse `{text}` as a date (expected `{config.DATE_FORMAT}`).\n"
            f"Example: `/birthday-set {_example(date(1990, 7, 4))}`"
        )

    was_update = database.set_birthday(user_id, username, bday.isoformat())
    action = "updated" if was_update else "set"
    display = bday.strftime("%d %B")  # e.g. "04 July" — always human-readable

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
        name = _display_name(row["user_id"], row["username"])
        lines.append(f"- {name}: {_fmt_date_range(start, end)}{label_str}")

    return _resp("\n".join(lines), response_type="in_channel")


# ---------------------------------------------------------------------------
# /holiday-notify (experimental) — holiday-add + email to administrator
# ---------------------------------------------------------------------------

def _send_admin_email(
    username: str,
    start: date,
    end: date,
    label: str | None,
    to_email: str,
) -> None:
    """Send a holiday notification email to the company administrator via SMTP."""
    date_range = _fmt_date_range(start, end)
    label_line = f"\nReason/Label: {label}" if label else ""

    body = (
        f"This is an automated notification from the Mattermost Holiday Bot.\n\n"
        f"@{username} has registered a holiday:\n"
        f"Dates: {date_range}{label_line}\n\n"
        f"Submitted via the /holiday-notify slash command."
    )

    msg = MIMEMultipart()
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = f"Holiday notification: @{username} ({date_range})"
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
        if config.SMTP_USE_TLS:
            smtp.starttls()
        if config.SMTP_USER and config.SMTP_PASSWORD:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.sendmail(config.SMTP_FROM, to_email, msg.as_string())


def cmd_holiday_user_rename(user_id: str, username: str, text: str) -> dict:
    """Set a display name alias for the invoking user."""
    alias = text.strip().lstrip("@")
    if not alias:
        current = database.get_alias(user_id)
        current_str = f" Currently set to **@{current}**." if current else " No alias set."
        return _resp(
            f"Usage: `/holiday-user-rename <display-name>`\n"
            f"Sets the name shown for you in all holiday bot output.{current_str}"
        )
    was_update = database.set_alias(user_id, alias)
    action = "updated" if was_update else "set"
    return _resp(f":white_check_mark: Display name {action} to **{alias}**.")


def cmd_holiday_notify(user_id: str, username: str, text: str) -> dict:
    """
    ⚠️ Experimental. Same as /holiday-add but also emails the company administrator.
    Requires COMPANY_ADMIN_EMAIL and SMTP settings in .env.
    """
    parsed = _parse_holiday_args(text)
    if isinstance(parsed, str):
        return _resp(parsed)

    start, end, label = parsed
    holiday_id = database.add_holiday(user_id, username, start.isoformat(), end.isoformat(), label)
    label_str = f": _{label}_" if label else ""
    base_msg = (
        f":white_check_mark: Holiday added (ID: **{holiday_id}**)\n"
        f"_{_fmt_date_range(start, end)}{label_str}_"
    )

    admin_email = config.COMPANY_ADMIN_EMAIL
    if not admin_email:
        date_range = _fmt_date_range(start, end)
        label_line = f"\nReason: {label}" if label else ""
        email_template = (
            f"Subject: Holiday Notification: {date_range}\n\n"
            f"Hi,\n\n"
            f"I wanted to let you know I will be on holiday from {_fmt_date(start)} to {_fmt_date(end)}{label_line}.\n\n"
            f"Please update your records accordingly.\n\n"
            f"Best regards,\n"
            f"{username}"
        )
        return _resp(
            base_msg + "\n\n"
            ":warning: No administrator email is configured. "
            "You can send the following email manually:\n"
            f"```\n{email_template}\n```"
        )

    try:
        _send_admin_email(username, start, end, label, admin_email)
        return _resp(base_msg + f"\n\n:email: Administrator notified at `{admin_email}`.")
    except Exception:
        logger.exception(
            "Failed to send admin email for holiday %d by %s.", holiday_id, username
        )
        return _resp(
            base_msg + "\n\n"
            ":warning: **Email failed to send.** Your holiday was saved. "
            "Check the bot logs and SMTP configuration."
        )
