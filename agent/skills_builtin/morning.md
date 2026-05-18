---
name: morning
description: Daily briefing — battery, weather, calendar, mail, and pending updates.
trigger: "morning briefing|daily standup|what's on today"
tools: [get_battery_status, get_weather, get_calendar_events, check_app_updates, read_emails, notify_user]
permissions: [allow_email, allow_calendar]
---

You are running the **morning** skill — a quick daily briefing. Be brisk:
one line per item, no marketing copy.

Gather, in parallel where possible:

1. `get_battery_status` — note % and charging state.
2. `get_weather` — current conditions + high/low.
3. `get_calendar_events` with lookahead_days=1.
4. `read_emails` with limit=5 (unread only).
5. `check_app_updates` — flag any with available updates.

Compose a single short briefing:

- **Today** — 1 sentence (weather + most important calendar event).
- **Battery** — single line if not on AC and below 50%; otherwise skip.
- **Calendar** — up to 4 bullets (time + title).
- **Inbox** — up to 3 bullets (sender + subject), only if anything is new.
- **Updates** — single line if anything is outdated; otherwise skip.

End by calling `notify_user(title='Morning briefing ready', body=<1-line summary>)`.
