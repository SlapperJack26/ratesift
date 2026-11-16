---
name: discord-team-ops
description: >-
  Send notifications, rich embeds, and file attachments to Discord channels via Incoming
  Webhooks, or perform two-way Discord channel operations (list channels, read messages,
  search history, create threads, and post replies) via the Discord MCP server. Use this
  skill whenever the user asks to message the team on Discord, read or summarize Discord
  channel discussions, reply to Discord threads, or set up/troubleshoot Discord access.
---

# Discord Team Ops Skill

Use this skill for both **one-way channel announcements/file sharing** (via Incoming Webhooks) and **two-way team collaboration** (reading channels, searching threads, and replying via the `discord` MCP server).

---

## Option 1: Post Notifications, Cards & Files via Webhook CLI

Run [`scripts/discord_notify.py`](./scripts/discord_notify.py) with Python 3.9+. Credentials are hot-loaded from [`.agents/discord_config.json`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/.agents/discord_config.json), the workspace `.env`, or `C:\Users\Dylan\.gemini\config\discord.env`.

### Examples

1. **Dry-run validation (no network request):**
   ```powershell
   python .agents/skills/discord-team-ops/scripts/discord_notify.py --title "Test Alert" --description "Integration ready" --color green --field "Mode=Dry Run" --dry-run
   ```

2. **Post a plain message or rich embed to a channel alias (`default`, `sales`, `support`, `ops`):**
   ```powershell
   python .agents/skills/discord-team-ops/scripts/discord_notify.py --channel sales --title "Tabi Connect Competitor Brief" --description "Price & feature breakdown ready for the team." --color blue --field "Starter Tier=$29/mo|inline" --field "Business Tier=$499/mo|inline" --footer "Posted by Antigravity"
   ```

3. **Attach a document or rate sheet (`.docx`, `.pdf`, `.xlsx`, `.csv`):**
   ```powershell
   python .agents/skills/discord-team-ops/scripts/discord_notify.py --channel sales --message "Updated Sales Rep Business API Setup Guide attached:" --file "outreach/11_Sales_Rep_Business_API_Setup_and_Troubleshooting_Guide.docx"
   ```

Supported `--color` presets: `blurple`, `blue`, `green`, `amber`, `red` (or hex `#5865F2`).

---

## Option 2: Two-Way Channel Access via `discord` MCP Server

When the `discord` MCP server (`.agents/mcp/discord_mcp_server.py`) is active, prefer calling these MCP tools directly:

1. **`discord_status`** — Verify webhook and bot configuration and confirm which Discord server (`guild`) the bot is connected to.
2. **`discord_list_channels`** — List all text/voice/forum/announcement channels and IDs in the server (auto-discovers `DISCORD_GUILD_ID` if omitted).
3. **`discord_read_messages`** — Read recent messages in chronological order (`channel_id`, optional `limit` 1–100).
4. **`discord_search_messages`** — Search recent messages in a channel by keyword (`query`) and optional `author` filter.
5. **`discord_send_message`** — Post a message, inline reply (`reply_to_message_id`), or rich embed into a channel or thread.
6. **`discord_create_thread`** — Start a new thread (from an existing `message_id` or standalone) and optionally post an opening `content` message.
7. **`discord_send_webhook`** — Post a formatted embed or file attachment via Incoming Webhook directly through MCP.

---

## Setup & Troubleshooting

If `discord_status` reports missing credentials or `DISCORD_WEBHOOK_URL` / `DISCORD_BOT_TOKEN` errors occur:
- Read [DISCORD_SETUP_GUIDE.md](./references/DISCORD_SETUP_GUIDE.md) and walk the user through pasting their webhook URL or bot token into [`.agents/discord_config.json`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/.agents/discord_config.json) (or `.env`).
- Credentials are **hot-loaded on every tool call**, so no IDE restart is required after saving the file.
