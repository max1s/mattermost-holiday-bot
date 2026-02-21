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


MATTERMOST_URL: str = _require("MATTERMOST_URL").rstrip("/")
MATTERMOST_TOKEN: str = _require("MATTERMOST_TOKEN")
MATTERMOST_TEAM_ID: str = _require("MATTERMOST_TEAM_ID")
MATTERMOST_CHANNEL_ID: str = _require("MATTERMOST_CHANNEL_ID")

BOT_PORT: int = int(os.getenv("BOT_PORT", "5000"))

# Database path — defaults to a permanent location that survives restarts
# regardless of which directory the bot is launched from.
_default_db = Path.home() / ".local" / "share" / "mattermost-holiday-bot" / "bot.db"
DB_PATH: Path = Path(os.getenv("DB_PATH", str(_default_db))).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

TIMEZONE: ZoneInfo = _load_timezone()

# Verification tokens for each slash command.
# Mattermost generates a unique token per registered slash command.
# Store each in .env and never commit them.
SLASH_TOKENS: dict[str, str] = {
    "holiday-add":    _require("SLASH_TOKEN_HOLIDAY_ADD"),
    "holiday-list":   _require("SLASH_TOKEN_HOLIDAY_LIST"),
    "holiday-delete": _require("SLASH_TOKEN_HOLIDAY_DELETE"),
    "birthday-set":   _require("SLASH_TOKEN_BIRTHDAY_SET"),
    "birthday-delete": _require("SLASH_TOKEN_BIRTHDAY_DELETE"),
    "away-today":     _require("SLASH_TOKEN_AWAY_TODAY"),
}
