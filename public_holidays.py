"""
public_holidays.py — Bank/national holiday lookups for the locales we display.

Wraps the `holidays` PyPI package. Exposes two helpers:
  - on_date(d)         -> list[(label, name)]  for a single day
  - in_range(start, e) -> list[(label, date, name)]  for a span (inclusive)

Locales are configured in LOCALES below. Each entry is (label, flag, country,
subdiv). To add or remove a locale, edit that list — nothing else changes.
"""

from datetime import date, timedelta

import holidays


LOCALES: list[tuple[str, str, str, str | None]] = [
    ("US",                "🇺🇸", "US", None),
    ("England",           "🇬🇧", "GB", "ENG"),
    ("Scotland",          "🇬🇧", "GB", "SCT"),
    ("France",            "🇫🇷", "FR", None),
    ("Germany (BW)",      "🇩🇪", "DE", "BW"),
]


_cache: dict[tuple[str, str | None], holidays.HolidayBase] = {}


def _calendar(country: str, subdiv: str | None) -> holidays.HolidayBase:
    key = (country, subdiv)
    cal = _cache.get(key)
    if cal is None:
        cal = holidays.country_holidays(country, subdiv=subdiv)
        _cache[key] = cal
    return cal


def _merge_same_flag(entries: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """
    Collapse adjacent entries that share the same (flag, name) by joining
    their labels with ", ". Input must already be in locale order.
    Returns [(label, flag, name)].
    """
    merged: list[tuple[str, str, str]] = []
    for label, flag, name in entries:
        if merged and merged[-1][1] == flag and merged[-1][2] == name:
            prev_label, prev_flag, prev_name = merged[-1]
            merged[-1] = (f"{prev_label}, {label}", prev_flag, prev_name)
        else:
            merged.append((label, flag, name))
    return merged


def on_date(d: date) -> list[tuple[str, str, str]]:
    """
    Return [(label, flag, name)] for every locale that has a holiday on d.
    Same-flag/same-name entries are merged (e.g. England + Scotland on May Day
    collapse to a single 'England, Scotland' entry).
    """
    raw = []
    for label, flag, country, subdiv in LOCALES:
        cal = _calendar(country, subdiv)
        name = cal.get(d)
        if name:
            raw.append((label, flag, name))
    return _merge_same_flag(raw)


def in_range(start: date, end: date) -> list[tuple[date, str, str, str]]:
    """
    Return [(date, label, flag, name)] for every locale-holiday in [start, end].
    Sorted by date, then by locale order. Same-flag/same-name entries on the
    same date are merged into a single entry with comma-joined labels.
    """
    out: list[tuple[date, str, str, str]] = []
    day = start
    while day <= end:
        for label, flag, name in on_date(day):
            out.append((day, label, flag, name))
        day += timedelta(days=1)
    return out
