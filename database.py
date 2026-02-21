"""
database.py — All SQLite access for the holiday bot.

All SQL lives here. No other module should import sqlite3 directly.
Uses WAL journal mode for safe concurrent access (Flask requests + scheduler).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Generator

DB_PATH = "bot.db"


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and indexes if they don't exist. Call once at startup."""
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS birthdays (
                user_id    TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                birth_date TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS holidays (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                username   TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date   TEXT NOT NULL,
                label      TEXT,
                CONSTRAINT chk_dates CHECK (start_date <= end_date)
            );

            CREATE INDEX IF NOT EXISTS idx_holidays_start
                ON holidays(start_date);

            CREATE INDEX IF NOT EXISTS idx_holidays_end
                ON holidays(end_date);
        """)


# ---------------------------------------------------------------------------
# Birthday CRUD
# ---------------------------------------------------------------------------

def set_birthday(user_id: str, username: str, birth_date: str) -> bool:
    """
    Upsert a birthday. Returns True if this was an update (existing row replaced),
    False if it was a new insert.
    """
    existing = get_birthday(user_id)
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO birthdays (user_id, username, birth_date) VALUES (?, ?, ?)",
            (user_id, username, birth_date),
        )
    return existing is not None


def get_birthday(user_id: str) -> sqlite3.Row | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM birthdays WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row


def delete_birthday(user_id: str) -> bool:
    """Returns True if a row was deleted."""
    with _conn() as conn:
        cursor = conn.execute("DELETE FROM birthdays WHERE user_id = ?", (user_id,))
    return cursor.rowcount > 0


def get_birthdays_in_range(start: date, end: date) -> list[sqlite3.Row]:
    """
    Return all birthdays whose month-day falls within [start, end].
    Handles year-boundary ranges (e.g. Dec 28 – Jan 3) correctly.
    The birth year is ignored — only month and day are compared.
    """
    start_md = start.strftime("%m-%d")
    end_md = end.strftime("%m-%d")

    with _conn() as conn:
        if start_md <= end_md:
            # Normal range within the same year portion
            rows = conn.execute(
                "SELECT * FROM birthdays "
                "WHERE strftime('%m-%d', birth_date) BETWEEN ? AND ? "
                "ORDER BY strftime('%m-%d', birth_date), username",
                (start_md, end_md),
            ).fetchall()
        else:
            # Year-wrapping range (e.g. '12-28' to '01-03')
            rows = conn.execute(
                "SELECT * FROM birthdays "
                "WHERE strftime('%m-%d', birth_date) >= ? "
                "   OR strftime('%m-%d', birth_date) <= ? "
                "ORDER BY strftime('%m-%d', birth_date), username",
                (start_md, end_md),
            ).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Holiday CRUD
# ---------------------------------------------------------------------------

def add_holiday(
    user_id: str,
    username: str,
    start_date: str,
    end_date: str,
    label: str | None,
) -> int:
    """Insert a holiday and return the new row ID."""
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO holidays (user_id, username, start_date, end_date, label) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, start_date, end_date, label),
        )
    return cursor.lastrowid


def get_upcoming_holidays(user_id: str, today: date) -> list[sqlite3.Row]:
    """Return holidays for a user whose end_date >= today, ordered by start_date."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays "
            "WHERE user_id = ? AND end_date >= ? "
            "ORDER BY start_date",
            (user_id, today.isoformat()),
        ).fetchall()
    return rows


def get_holiday_by_id(holiday_id: int, user_id: str) -> sqlite3.Row | None:
    """Fetch a single holiday, verifying ownership."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM holidays WHERE id = ? AND user_id = ?",
            (holiday_id, user_id),
        ).fetchone()
    return row


def delete_holiday(holiday_id: int, user_id: str) -> bool:
    """
    Delete a holiday by ID, verifying ownership.
    Returns True if deleted, False if not found or not owned by user_id.
    The caller gets the same response in both cases to avoid leaking ID ownership.
    """
    with _conn() as conn:
        cursor = conn.execute(
            "DELETE FROM holidays WHERE id = ? AND user_id = ?",
            (holiday_id, user_id),
        )
    return cursor.rowcount > 0


def get_holidays_overlapping_range(start: date, end: date) -> list[sqlite3.Row]:
    """
    Return all holidays (all users) that overlap with [start, end].
    Overlap condition: holiday.start_date <= range_end AND holiday.end_date >= range_start.
    Ordered by username then start_date.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays "
            "WHERE start_date <= ? AND end_date >= ? "
            "ORDER BY username, start_date",
            (end.isoformat(), start.isoformat()),
        ).fetchall()
    return rows


def get_holidays_starting_on(target_date: date) -> list[sqlite3.Row]:
    """Return holidays (all users) whose start_date equals target_date."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays WHERE start_date = ? ORDER BY username",
            (target_date.isoformat(),),
        ).fetchall()
    return rows


def get_holidays_overlapping_date(target_date: date) -> list[sqlite3.Row]:
    """Return holidays (all users) that cover target_date (for /away-today)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays "
            "WHERE start_date <= ? AND end_date >= ? "
            "ORDER BY username",
            (target_date.isoformat(), target_date.isoformat()),
        ).fetchall()
    return rows
