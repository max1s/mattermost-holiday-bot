"""
mattermost.py — Wrapper around mattermostdriver for posting messages.

All other modules call these functions; none import mattermostdriver directly.
Uses a lazy singleton so the driver connects on first use, not at import time.
"""

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine

from mattermostdriver import Driver

import config

logger = logging.getLogger(__name__)

_driver: Driver | None = None


def _get_driver() -> Driver:
    """Return the singleton Driver, connecting on first call."""
    global _driver
    if _driver is None:
        parsed = config.MATTERMOST_URL
        if parsed.startswith("https://"):
            scheme = "https"
            host = parsed[len("https://"):]
            port = 443
        elif parsed.startswith("http://"):
            scheme = "http"
            host = parsed[len("http://"):]
            port = 80
        else:
            scheme = "https"
            host = parsed
            port = 443

        if ":" in host:
            host, port_str = host.rsplit(":", 1)
            port = int(port_str)

        _driver = Driver(
            {
                "url": host,
                "token": config.MATTERMOST_TOKEN,
                "scheme": scheme,
                "port": port,
                "verify": config.VERIFY_SSL,
            }
        )
        _driver.login()
        logger.info("Mattermost driver connected to %s", config.MATTERMOST_URL)
    return _driver


def post_to_channel(channel_id: str, message: str) -> None:
    """Post a message to a channel by ID."""
    _get_driver().posts.create_post(
        options={"channel_id": channel_id, "message": message}
    )


def post_to_announcement_channel(message: str) -> None:
    """Post to the configured announcement channel."""
    post_to_channel(config.MATTERMOST_CHANNEL_ID, message)


def get_bot_user_id() -> str:
    """Return the bot's own Mattermost user ID."""
    return _get_driver().users.get_user("me")["id"]


_username_cache: dict[str, str] = {}


def get_username(user_id: str) -> str | None:
    """
    Look up a user's current Mattermost username by ID. Cached for the
    lifetime of the process so repeat calls in a single announcement are cheap.
    Returns None if the user is unknown or the API call fails — callers
    should fall back to a stored value.
    """
    cached = _username_cache.get(user_id)
    if cached is not None:
        return cached
    try:
        username = _get_driver().users.get_user(user_id).get("username")
    except Exception:
        logger.exception("Failed to look up username for user_id=%s", user_id)
        return None
    if username:
        _username_cache[user_id] = username
    return username


def start_websocket_listener(handler: Callable[..., Coroutine]) -> threading.Thread:
    """
    Start the Mattermost WebSocket event listener in a background daemon thread.
    The handler must be an async function that accepts a raw event string.
    """
    driver = _get_driver()  # ensure driver is connected before spawning thread

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            driver.init_websocket(handler)
        except Exception:
            logger.exception("WebSocket listener exited unexpectedly.")

    thread = threading.Thread(target=_run, daemon=True, name="mattermost-websocket")
    thread.start()
    logger.info("WebSocket listener thread started.")
    return thread
