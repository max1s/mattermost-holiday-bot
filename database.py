"""
database.py — All SQLite access for the holiday bot.

All SQL lives here. No other module should import sqlite3 directly.
Uses WAL journal mode for safe concurrent access (Flask requests + scheduler).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Generator

import config


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(config.DB_PATH)
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

            CREATE TABLE IF NOT EXISTS user_aliases (
                user_id  TEXT PRIMARY KEY,
                alias    TEXT NOT NULL COLLATE NOCASE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_aliases_alias
                ON user_aliases(alias COLLATE NOCASE);

            CREATE TABLE IF NOT EXISTS holidays (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                username   TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date   TEXT NOT NULL,
                label      TEXT,
                start_part TEXT NOT NULL DEFAULT 'full',
                end_part   TEXT NOT NULL DEFAULT 'full',
                CONSTRAINT chk_dates CHECK (start_date <= end_date)
            );

            CREATE INDEX IF NOT EXISTS idx_holidays_start
                ON holidays(start_date);

            CREATE INDEX IF NOT EXISTS idx_holidays_end
                ON holidays(end_date);
        """)
        # Idempotent migration: add start_part/end_part to pre-existing holidays
        # tables. SQLite's CREATE TABLE IF NOT EXISTS won't add new columns to
        # an already-created table, so add them by hand if missing.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(holidays)")}
        if "start_part" not in cols:
            conn.execute("ALTER TABLE holidays ADD COLUMN start_part TEXT NOT NULL DEFAULT 'full'")
        if "end_part" not in cols:
            conn.execute("ALTER TABLE holidays ADD COLUMN end_part   TEXT NOT NULL DEFAULT 'full'")
        # Migrate legacy single-day half-days where the half-period was stored
        # in the free-text label instead of the new columns. Case-insensitive
        # match catches user variants like "Afternoon" or " morning ".
        conn.execute(
            "UPDATE holidays "
            "   SET start_part = LOWER(TRIM(label)), "
            "       end_part   = LOWER(TRIM(label)), "
            "       label      = NULL "
            " WHERE LOWER(TRIM(label)) IN ('morning','afternoon') "
            "   AND start_date = end_date "
            "   AND start_part = 'full' AND end_part = 'full'"
        )


# ---------------------------------------------------------------------------
# User aliases
# ---------------------------------------------------------------------------

def set_alias(user_id: str, alias: str) -> bool:
    """Set or update a display name alias. Returns True if this was an update."""
    existing = get_alias(user_id)
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_aliases (user_id, alias) VALUES (?, ?)",
            (user_id, alias),
        )
    return existing is not None


def get_alias(user_id: str) -> str | None:
    """Return the alias for a user_id, or None if not set."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT alias FROM user_aliases WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["alias"] if row else None


def get_user_id_by_name(name: str) -> str | None:
    """Look up a user_id by alias (case-insensitive). Returns None if not found."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_aliases WHERE alias = ?", (name,)
        ).fetchone()
    return row["user_id"] if row else None


def get_all_aliases() -> dict[str, str]:
    """Return a dict of user_id -> alias for all users with aliases set."""
    with _conn() as conn:
        rows = conn.execute("SELECT user_id, alias FROM user_aliases").fetchall()
    return {row["user_id"]: row["alias"] for row in rows}


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
    start_part: str = "full",
    end_part: str = "full",
) -> int:
    """Insert a holiday and return the new row ID."""
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO holidays "
            "(user_id, username, start_date, end_date, label, start_part, end_part) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, start_date, end_date, label, start_part, end_part),
        )
    return cursor.lastrowid


def find_duplicate_holiday(
    user_id: str,
    start_date: str,
    end_date: str,
    label: str | None,
    start_part: str,
    end_part: str,
) -> int | None:
    """
    Return the id of an existing holiday with identical fields for this user,
    or None. Used to prevent accidental duplicate inserts that would cause
    every announcement about that day to fire twice.
    """
    with _conn() as conn:
        # NULL = NULL is false in SQL, so the label clause is split.
        if label is None:
            row = conn.execute(
                "SELECT id FROM holidays "
                "WHERE user_id = ? AND start_date = ? AND end_date = ? "
                "  AND label IS NULL AND start_part = ? AND end_part = ?",
                (user_id, start_date, end_date, start_part, end_part),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM holidays "
                "WHERE user_id = ? AND start_date = ? AND end_date = ? "
                "  AND label = ? AND start_part = ? AND end_part = ?",
                (user_id, start_date, end_date, label, start_part, end_part),
            ).fetchone()
    return row["id"] if row else None


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


def get_all_upcoming_holidays(today: date) -> list[sqlite3.Row]:
    """Return all upcoming holidays for all users, ordered by start_date then username."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays "
            "WHERE end_date >= ? "
            "ORDER BY start_date, username",
            (today.isoformat(),),
        ).fetchall()
    return rows


def get_upcoming_holidays_by_user_id(user_id: str, today: date) -> list[sqlite3.Row]:
    """Return upcoming holidays for a specific user_id, ordered by start_date."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays "
            "WHERE user_id = ? AND end_date >= ? "
            "ORDER BY start_date",
            (user_id, today.isoformat()),
        ).fetchall()
    return rows


def get_upcoming_holidays_by_username(username: str, today: date) -> list[sqlite3.Row]:
    """Return upcoming holidays for a specific username, ordered by start_date."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM holidays "
            "WHERE username = ? AND end_date >= ? "
            "ORDER BY start_date",
            (username, today.isoformat()),
        ).fetchall()
    return rows


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
