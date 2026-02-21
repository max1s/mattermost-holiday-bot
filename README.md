# Mattermost Holiday Bot

A Mattermost bot that lets your team track holidays and birthdays via slash commands, with automatic weekly summaries and daily reminders.

## Features

### Slash Commands

| Command | Description |
|---------|-------------|
| `/holiday-add <DD-MM-YYYY> [DD-MM-YYYY] [label]` | Add a holiday (single day or date range, optional label) |
| `/holiday-list` | List your upcoming holidays with their IDs |
| `/holiday-delete <ID>` | Delete one of your holidays |
| `/holiday-help` | Show full help for all commands |
| `/birthday-set <DD-MM-YYYY>` | Set or update your birthday |
| `/birthday-delete` | Remove your birthday |
| `/away-today` | See everyone who is away today |
| `/holiday-notify <DD-MM-YYYY> [DD-MM-YYYY] [label]` | ⚠️ Experimental: add holiday + email the company administrator |

> **Date format** defaults to `DD-MM-YYYY` (European). Change with the `DATE_FORMAT` env var — see Configuration below.

### Scheduled Announcements

- **Monday 9AM** — Weekly summary of birthdays and holidays for this week and next
- **Weekdays 9AM** — Holiday reminders:
  - One-week reminder when someone's holiday starts in 7 days
  - One-day reminder when someone's holiday starts tomorrow

---

## Setup

### Requirements

- Python 3.10+
- A Mattermost server (with access to create integrations)
- Network connectivity: Mattermost must be able to POST to the bot server (for slash commands), and the bot must be able to reach Mattermost (for posting messages)

### 1. Clone and install

```bash
git clone https://github.com/max1s/mattermost-holiday-bot.git
cd mattermost-holiday-bot

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create a bot account in Mattermost

1. Go to **Main Menu → Integrations → Bot Accounts**
2. Click **Add Bot Account**
3. Set a username (e.g. `holiday-bot`), display name, and description
4. Click **Create Bot Account**
5. Copy the generated **access token** — this is your `MATTERMOST_TOKEN`
6. Add the bot to the channel where it should post announcements

### 3. Register slash commands in Mattermost

Go to **Main Menu → Integrations → Slash Commands → Add Slash Command** and create one entry for each command below.

For each command, set:
- **Request URL**: `http://<your-bot-host>:<BOT_PORT>/slash/<command-name>`
- **Request Method**: POST
- **Autocomplete**: Enable and fill in description/hint if desired

| Command trigger | Request URL path | Token env var |
|----------------|-----------------|---------------|
| `holiday-add` | `/slash/holiday-add` | `SLASH_TOKEN_HOLIDAY_ADD` |
| `holiday-list` | `/slash/holiday-list` | `SLASH_TOKEN_HOLIDAY_LIST` |
| `holiday-delete` | `/slash/holiday-delete` | `SLASH_TOKEN_HOLIDAY_DELETE` |
| `holiday-help` | `/slash/holiday-help` | `SLASH_TOKEN_HOLIDAY_HELP` |
| `holiday-notify` | `/slash/holiday-notify` | `SLASH_TOKEN_HOLIDAY_NOTIFY` |
| `birthday-set` | `/slash/birthday-set` | `SLASH_TOKEN_BIRTHDAY_SET` |
| `birthday-delete` | `/slash/birthday-delete` | `SLASH_TOKEN_BIRTHDAY_DELETE` |
| `away-today` | `/slash/away-today` | `SLASH_TOKEN_AWAY_TODAY` |

After creating each slash command, Mattermost shows you a **token**. Copy each token into your `.env` file (see step 4).

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
MATTERMOST_URL=https://mattermost.example.com
MATTERMOST_TOKEN=your_bot_token_here

# Team ID — find in Admin Console > Teams, or via API: GET /api/v4/teams
MATTERMOST_TEAM_ID=your_team_id_here

# Channel ID for automated announcements (bot must be a member)
# Find via: Admin Console > Channels, or the channel URL
MATTERMOST_CHANNEL_ID=your_channel_id_here

BOT_PORT=5000
TIMEZONE=Europe/London   # Any valid IANA timezone name

# Date format — default is DD-MM-YYYY (European). See .env.example for options.
# DATE_FORMAT=%d-%m-%Y

# Optional: email settings for /holiday-notify
# COMPANY_ADMIN_EMAIL=admin@example.com
# SMTP_HOST=localhost
# SMTP_PORT=587
# SMTP_USER=holiday-bot@example.com
# SMTP_PASSWORD=secret

SLASH_TOKEN_HOLIDAY_ADD=token_from_mattermost
SLASH_TOKEN_HOLIDAY_LIST=token_from_mattermost
SLASH_TOKEN_HOLIDAY_DELETE=token_from_mattermost
SLASH_TOKEN_HOLIDAY_HELP=token_from_mattermost
SLASH_TOKEN_HOLIDAY_NOTIFY=token_from_mattermost
SLASH_TOKEN_BIRTHDAY_SET=token_from_mattermost
SLASH_TOKEN_BIRTHDAY_DELETE=token_from_mattermost
SLASH_TOKEN_AWAY_TODAY=token_from_mattermost
```

> **Never commit `.env`** — it contains secrets. It is already in `.gitignore`.

### 5. Run the bot

**Development:**
```bash
python bot.py
```

**Production (recommended — single worker only):**
```bash
pip install gunicorn
gunicorn --workers 1 --bind 0.0.0.0:5000 "bot:app"
```

> Use `--workers 1` with Gunicorn. Multiple workers would each start their own APScheduler instance, sending duplicate announcements.

**As a systemd service:**

```ini
# /etc/systemd/system/holiday-bot.service
[Unit]
Description=Mattermost Holiday Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/opt/mattermost-holiday-bot
ExecStart=/opt/mattermost-holiday-bot/.venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/mattermost-holiday-bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable holiday-bot
sudo systemctl start holiday-bot
```

### 6. Verify

Check the bot is running:
```bash
curl http://localhost:5000/health
# → {"status": "ok"}
```

Test a slash command manually (replace token/user values):
```bash
curl -X POST http://localhost:5000/slash/away-today \
  -d "token=YOUR_SLASH_TOKEN&user_id=user123&user_name=testuser&text="
```

---

## Command Examples

```
/holiday-add 2026-08-03
/holiday-add 2026-08-03 2026-08-07
/holiday-add 2026-08-03 2026-08-07 Summer holiday

/holiday-list
/holiday-delete 42

/birthday-set 1990-07-04
/birthday-delete

/away-today
```

---

## Architecture

```
bot.py          Flask entrypoint + APScheduler startup
config.py       Environment variable loading (fail-fast)
database.py     SQLite CRUD (WAL mode, all SQL here)
commands.py     Slash command handler functions
scheduler.py    Scheduled job functions (weekly summary, daily reminders)
mattermost.py   Outbound Mattermost API wrapper
```

- **Database**: SQLite (`bot.db`, created on first run, excluded from git)
- **Timezone**: All date logic uses the configured `TIMEZONE` — never the server's system time
- **Token security**: Slash command tokens verified with `hmac.compare_digest`

---

## Finding Team ID and Channel ID

**Via the Mattermost API** (with your bot token):
```bash
# List teams
curl -H "Authorization: Bearer YOUR_BOT_TOKEN" \
  https://mattermost.example.com/api/v4/teams

# List channels in a team
curl -H "Authorization: Bearer YOUR_BOT_TOKEN" \
  https://mattermost.example.com/api/v4/teams/TEAM_ID/channels
```

**Via the Mattermost UI**:
- Team ID: Admin Console → Teams → click team → ID shown in URL
- Channel ID: open the channel, click the name → **View Info** → ID shown, or copy from the URL
