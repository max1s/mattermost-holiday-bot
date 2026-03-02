"""
config.py — Load and validate all environment variables at startup.

Uses os.environ[] (not os.getenv) for required values so the bot
crashes immediately with a clear error if misconfigured.
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' is not set. See .env.example.")
    return value


def _load_timezone() -> ZoneInfo:
    tz_name = os.getenv("TIMEZONE", "UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise RuntimeError(
            f"Unknown timezone '{tz_name}'. "
            "Use a valid IANA timezone name, e.g. 'Europe/London' or 'America/New_York'."
        )


def _load_date_format() -> str:
    fmt = os.getenv("DATE_FORMAT", "%d-%m-%Y")
    # Sanity-check: make sure it round-trips on a known date
    from datetime import date, datetime
    try:
        probe = date(2026, 3, 15)
        datetime.strptime(probe.strftime(fmt), fmt)
    except (ValueError, TypeError):
        raise RuntimeError(
            f"DATE_FORMAT '{fmt}' is not a valid strftime format string. "
            "Examples: '%d-%m-%Y' (EU), '%Y-%m-%d' (ISO), '%m/%d/%Y' (US)."
        )
    return fmt


MATTERMOST_URL: str = _require("MATTERMOST_URL").rstrip("/")
MATTERMOST_TOKEN: str = _require("MATTERMOST_TOKEN")
MATTERMOST_TEAM_ID: str = _require("MATTERMOST_TEAM_ID")
MATTERMOST_CHANNEL_ID: str = _require("MATTERMOST_CHANNEL_ID")

BOT_PORT: int = int(os.getenv("BOT_PORT", "5000"))
VERIFY_SSL: bool = os.getenv("VERIFY_SSL", "true").lower() not in ("0", "false", "no")

# Database path — defaults to a permanent location that survives restarts
# regardless of which directory the bot is launched from.
_default_db = Path.home() / ".local" / "share" / "mattermost-holiday-bot" / "bot.db"
DB_PATH: Path = Path(os.getenv("DB_PATH", str(_default_db))).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

TIMEZONE: ZoneInfo = _load_timezone()

# Date format used for both user input and display throughout the bot.
# Default: DD-MM-YYYY (European). Override with DATE_FORMAT env var.
# Common options:
#   %d-%m-%Y  →  25-12-2026  (European, default)
#   %d/%m/%Y  →  25/12/2026  (European with slashes)
#   %Y-%m-%d  →  2026-12-25  (ISO 8601)
#   %m/%d/%Y  →  12/25/2026  (American)
DATE_FORMAT: str = _load_date_format()

# ---------------------------------------------------------------------------
# Email settings (optional — only needed for /holiday-notify)
# ---------------------------------------------------------------------------
COMPANY_ADMIN_EMAIL: str | None = os.getenv("COMPANY_ADMIN_EMAIL")
SMTP_HOST: str = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str | None = os.getenv("SMTP_USER")
SMTP_PASSWORD: str | None = os.getenv("SMTP_PASSWORD")
SMTP_FROM: str = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "holiday-bot@localhost"
SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Slash command verification tokens
# ---------------------------------------------------------------------------
# Mattermost generates a unique token per registered slash command.
# Store each in .env and never commit them.
SLASH_TOKENS: dict[str, str] = {
    "holiday-add":    _require("SLASH_TOKEN_HOLIDAY_ADD"),
    "holiday-list":   _require("SLASH_TOKEN_HOLIDAY_LIST"),
    "holiday-delete": _require("SLASH_TOKEN_HOLIDAY_DELETE"),
    "holiday-help":   _require("SLASH_TOKEN_HOLIDAY_HELP"),
    "holiday-notify": _require("SLASH_TOKEN_HOLIDAY_NOTIFY"),
    "holiday-user-rename": _require("SLASH_TOKEN_HOLIDAY_USER_RENAME"),
    "birthday-set":   _require("SLASH_TOKEN_BIRTHDAY_SET"),
    "birthday-delete": _require("SLASH_TOKEN_BIRTHDAY_DELETE"),
    "away-today":     _require("SLASH_TOKEN_AWAY_TODAY"),
}
