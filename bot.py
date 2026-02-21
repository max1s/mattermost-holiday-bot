"""
bot.py — Flask app entrypoint.

Registers all slash command routes, verifies Mattermost tokens,
and starts the APScheduler background scheduler and WebSocket listener.
"""

import hmac
import logging
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, abort, jsonify, request

import commands
import config
import database
import events
import mattermost
import scheduler as sched_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

def _verify_token(command_name: str, received: str) -> bool:
    expected = config.SLASH_TOKENS.get(command_name)
    if not expected:
        return False
    return hmac.compare_digest(expected, received)


def _parse_slash_request() -> tuple[str, str, str]:
    user_id  = request.form.get("user_id", "")
    username = request.form.get("user_name", "")
    text     = request.form.get("text", "").strip()
    return user_id, username, text


def _guard(command_name: str) -> tuple[str, str, str]:
    token = request.form.get("token", "")
    if not _verify_token(command_name, token):
        logger.warning("Invalid token for command '%s'.", command_name)
        abort(401)
    return _parse_slash_request()


def _handle(fn):
    try:
        return jsonify(fn())
    except Exception:
        logger.exception("Unhandled error in slash command handler.")
        return jsonify(
            {"response_type": "ephemeral", "text": ":x: An internal error occurred. Please try again."}
        )


# ---------------------------------------------------------------------------
# Slash command routes
# ---------------------------------------------------------------------------

@app.route("/slash/holiday-add", methods=["POST"])
def route_holiday_add():
    user_id, username, text = _guard("holiday-add")
    return _handle(lambda: commands.cmd_holiday_add(user_id, username, text))


@app.route("/slash/holiday-list", methods=["POST"])
def route_holiday_list():
    user_id, username, text = _guard("holiday-list")
    return _handle(lambda: commands.cmd_holiday_list(user_id))


@app.route("/slash/holiday-delete", methods=["POST"])
def route_holiday_delete():
    user_id, username, text = _guard("holiday-delete")
    return _handle(lambda: commands.cmd_holiday_delete(user_id, text))


@app.route("/slash/holiday-help", methods=["POST"])
def route_holiday_help():
    _guard("holiday-help")
    return _handle(lambda: commands.cmd_help())


@app.route("/slash/holiday-notify", methods=["POST"])
def route_holiday_notify():
    user_id, username, text = _guard("holiday-notify")
    return _handle(lambda: commands.cmd_holiday_notify(user_id, username, text))


@app.route("/slash/birthday-set", methods=["POST"])
def route_birthday_set():
    user_id, username, text = _guard("birthday-set")
    return _handle(lambda: commands.cmd_birthday_set(user_id, username, text))


@app.route("/slash/birthday-delete", methods=["POST"])
def route_birthday_delete():
    user_id, username, text = _guard("birthday-delete")
    return _handle(lambda: commands.cmd_birthday_delete(user_id))


@app.route("/slash/away-today", methods=["POST"])
def route_away_today():
    _guard("away-today")
    return _handle(lambda: commands.cmd_away_today())


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def _start_scheduler() -> BackgroundScheduler:
    tz = config.TIMEZONE
    scheduler = BackgroundScheduler(timezone=str(tz))

    scheduler.add_job(
        sched_jobs.job_weekly_summary,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=tz),
        id="weekly_summary",
        name="Weekly birthday & holiday summary",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        sched_jobs.job_daily_reminders,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=tz),
        id="daily_reminders",
        name="Daily holiday reminders",
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info("Scheduler started (timezone: %s).", tz)
    return scheduler


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        database.init_db()
        logger.info("Database initialised at %s", config.DB_PATH)
    except Exception as exc:
        logger.critical("Failed to initialise database: %s", exc)
        sys.exit(1)

    _scheduler = _start_scheduler()

    # Start WebSocket listener for real-time events (e.g. bot added to channel)
    try:
        mattermost.start_websocket_listener(events.handle_event)
    except Exception as exc:
        # Non-fatal — bot still works without WebSocket; channel-join greeting won't fire
        logger.warning("Could not start WebSocket listener: %s", exc)

    try:
        app.run(host="0.0.0.0", port=config.BOT_PORT, debug=False)
    finally:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
