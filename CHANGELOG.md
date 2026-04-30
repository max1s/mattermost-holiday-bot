# Patch notes

Running log of user-visible changes, newest first. Each entry covers a deployment cycle (kill bot → edit → restart). Older changes that predate this log live in `git log`.

## 2026-04-30 (docs)

### Documentation
- README: documented public/bank-holiday support (locales, dedup behaviour, where they appear).
- README + `.env.example`: added the missing `holiday-user-rename` slash command to the registration table and `SLASH_TOKEN_HOLIDAY_USER_RENAME` env var (the command itself has been live since `b0810e6`; only the setup docs were out of date).
- README: link to `CHANGELOG.md`.

## 2026-04-30

### Added
- **Partial-day boundaries**: `/holiday-add` now accepts a `:am` / `:pm` (or `:morning` / `:afternoon`) suffix on either date.
  - `2026-08-03:am` — morning half-day
  - `2026-08-03:pm 2026-08-07:am` — off from Mon afternoon through Fri morning (4 days)
  - `2026-08-03:pm 2026-08-07` — leave Mon at lunch, off the rest of the week (4.5 days)
  - Legacy `<date> morning|afternoon` still parses.
- **Schema**: `holidays.start_part` and `holidays.end_part` (TEXT, default `'full'`). `init_db` runs an idempotent `ALTER TABLE` migration.
- **Legacy half-day backfill**: rows whose label matched `morning`/`afternoon` (case-insensitive) on a single date are auto-migrated to `start_part = end_part = <part>`, label cleared.
- **Fractional days** in announcements where one boundary is partial (e.g. `4.5 days`).
- `/away-today` flags partial-only days with `_(morning only)_` / `_(afternoon only)_`.
- README + `/holiday-help` examples updated for the new syntax.

### Fixed
- **Past-but-this-week holidays no longer appear in the weekly summary.** A holiday whose `end_date < today` was being included by `get_holidays_overlapping_range` and then triggering the in-progress branch, producing nonsense like `-1 days more`. Now filtered out at the top of `job_weekly_summary`.

## 2026-04-27

### Added
- **Public/bank holidays** for US, England, Scotland, France, Germany (Baden-Württemberg) appear in `/holiday-list all`, `/away-today`, and the Monday weekly summary.
  - Library: `holidays>=0.50` (PyPI).
  - Locales configured at the top of `public_holidays.py` — edit that list to add or remove jurisdictions.
- Same-flag/same-name entries on the same date are collapsed (e.g. `England, Scotland: May Day` instead of two lines).

### Fixed
- **Stale display names**: announcement output now resolves the current Mattermost username via `users.get_user(user_id)` rather than trusting the stored row value (which gets frozen at insert time and goes wrong if the user later renames themselves on Mattermost). Aliases set via `/holiday-user-rename` still take precedence; the stored username remains as a fallback if the live lookup fails.
- One-off republish of today's weekly summary so the channel reflected the corrected display names.

## 2026-04-24

### Added
- This `CHANGELOG.md` (seeded retroactively with the public-holiday work that landed today and the partial-day work that landed 2026-04-30).
- Initial public-holiday integration (US, UK, France, Germany BW). Superseded by the 2026-04-27 split that broke UK into England + Scotland.
</content>
</invoke>