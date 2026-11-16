# Free Discord Setup Guide for Antigravity Team Ops

Discord is 100% free with unlimited message history, unlimited Incoming Webhooks, and free two-way Bot API access.

Follow **Part A** (~1 minute) for **Option 1 (Webhook notifications & file uploads)**, and **Part B** (~4 minutes) for **Option 2 (Two-Way Discord Bot + MCP Server)**.

---

## Part A: Create Your Private Team Server & Webhook (Option 1)

1. **Create a Private Server (if you don't have one yet):**
   - Open Discord (desktop or browser) → click **`+` (Add a Server)** in the left sidebar → **Create My Own** → **For a club or community** → name it (e.g., `Quotelytics Team`).
   - Create text channels such as `#general`, `#sales-onboarding`, `#support`, and `#ops`.

2. **Generate an Incoming Webhook URL (10 seconds per channel):**
   - Hover over the channel you want Antigravity to post into (e.g., `#sales-onboarding`) → click the **gear icon (`Edit Channel`)**.
   - Go to **Integrations** → **Webhooks** → click **New Webhook**.
   - Optionally rename it to `Antigravity` → click **Copy Webhook URL**.

3. **Save the Webhook URL:**
   - Open [`c:\Users\Dylan\Documents\antigravity\quick-hertz\.agents\discord_config.json`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/.agents/discord_config.json) (gitignored, ready to edit) — or `.env` / `C:\Users\Dylan\.gemini\config\discord.env`.
   - Paste your URL(s) into `discord_config.json`:
     ```json
     {
       "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN",
       "DISCORD_SALES_WEBHOOK_URL": "https://discord.com/api/webhooks/YOUR_SALES_ID/YOUR_TOKEN",
       "DISCORD_SUPPORT_WEBHOOK_URL": "https://discord.com/api/webhooks/YOUR_SUPPORT_ID/YOUR_TOKEN",
       "DISCORD_OPS_WEBHOOK_URL": "https://discord.com/api/webhooks/YOUR_OPS_ID/YOUR_TOKEN"
     }
     ```
   - *(Tip: If you only create one webhook and set `DISCORD_WEBHOOK_URL`, all channel aliases automatically fall back to it.)*

---

## Part B: Create Your Free Two-Way Discord Bot (Option 2)

1. **Create the Application:**
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications) and sign in.
   - Click **New Application** (top right) → name it `Quotelytics Antigravity` → click **Create**.

2. **Enable Message Reading & Copy the Bot Token:**
   - In the left menu, click **Bot**.
   - Scroll down to **Privileged Gateway Intents** and toggle **ON**:
     - **Message Content Intent** *(Required so Antigravity can read channel message text and search history!)*
   - Scroll up and click **Reset Token** → confirm → click **Copy** to copy your Bot Token.
   - Paste it into [`discord_config.json`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/.agents/discord_config.json) (or `.env`):
     ```json
     "DISCORD_BOT_TOKEN": "YOUR_COPIED_BOT_TOKEN_HERE"
     ```

3. **Invite the Bot to Your Server:**
   - In the Developer Portal left menu, click **OAuth2** → **URL Generator**.
   - Under **Scopes**, check **`bot`**.
   - Under **Bot Permissions**, check:
     - **View Channels**
     - **Send Messages**
     - **Send Messages in Threads**
     - **Create Public Threads**
     - **Read Message History**
     - **Embed Links**
     - **Attach Files**
   - Copy the **Generated URL** at the bottom, paste it into your browser, select your server, and click **Authorize**.

4. **Optional: Set `DISCORD_GUILD_ID`:**
   - `DISCORD_GUILD_ID` is **auto-discovered automatically** if your bot is in one server.
   - If your bot is in multiple servers and you want to pin a specific one: in Discord, enable **User Settings → Advanced → Developer Mode**, right-click your server icon → **Copy Server ID**, and set `"DISCORD_GUILD_ID"` in `discord_config.json` (or `.env`).

---

## Verification

No restart is needed after saving `discord_config.json` (or `.env` / `discord.env`). Simply ask Antigravity:
- *"Check our Discord status and list all channels"*
- *"Send a test message to Discord"*
