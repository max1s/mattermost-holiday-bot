"""
events.py — Mattermost WebSocket event handler.

Listens for real-time events and reacts to them:
  - user_added: if the bot itself was added to a channel, post a welcome/help message.
"""

import json
import logging

import commands
import mattermost

logger = logging.getLogger(__name__)

_bot_user_id: str | None = None


def _get_bot_user_id() -> str:
    """Cached lookup of the bot's own user ID."""
    global _bot_user_id
    if _bot_user_id is None:
        _bot_user_id = mattermost.get_bot_user_id()
    return _bot_user_id


async def handle_event(event: str) -> None:
    """
    Async handler called by mattermostdriver for each WebSocket event.
    Events arrive as JSON strings.
    """
    try:
        data = json.loads(event)
    except (json.JSONDecodeError, TypeError):
        return

    event_type = data.get("event")

    if event_type == "user_added":
        _handle_user_added(data)


def _handle_user_added(data: dict) -> None:
    """Post a welcome message when the bot is added to a channel."""
    event_data = data.get("data", {})
    broadcast = data.get("broadcast", {})

    user_id = event_data.get("user_id")
    channel_id = broadcast.get("channel_id")

    if not channel_id:
        return

    try:
        bot_id = _get_bot_user_id()
    except Exception:
        logger.exception("Could not retrieve bot user ID.")
        return

    if user_id != bot_id:
        return

    logger.info("Bot added to channel %s — posting welcome message.", channel_id)
    try:
        mattermost.post_to_channel(channel_id, commands.help_text())
    except Exception:
        logger.exception("Failed to post welcome message to channel %s.", channel_id)
