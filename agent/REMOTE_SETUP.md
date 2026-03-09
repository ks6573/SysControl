# SysControl Remote Bridge — Setup Guide

This guide walks you through connecting the SysControl agent to **Telegram**,
**WhatsApp**, and **Facebook Messenger** so you can send commands from your phone.

---

## Prerequisites

Install the cloudflare tunnel once (it creates a free public URL):

```bash
# macOS
brew install cloudflared

# or direct download: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
```

Install the new Python dependencies:

```bash
cd /path/to/SyscontrolMCP
uv sync
```

---

## Step 1 — Start the Cloudflare Tunnel

Open a dedicated terminal and keep it running:

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

It will print a URL like `https://random-words.trycloudflare.com`. **Copy this URL** — you'll use it in every platform below.

> The URL changes every time you restart the tunnel. A free Cloudflare account lets you create a persistent named tunnel — see [Cloudflare Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).

---

## Step 2 — Create the Config File

Run remote.py once to generate the template:

```bash
uv run remote.py
```

This creates `~/.syscontrol/remote_config.json`. Open it and fill it in as you complete each platform below.

---

## Step 3 — Telegram

### 3a. Create a bot

1. Open Telegram → search for **@BotFather**
2. Send `/newbot` → follow prompts → you receive a token like `123456:ABC-DEF...`
3. Paste the token into config:
   ```json
   "telegram": { "enabled": true, "token": "123456:ABC-DEF..." }
   ```

### 3b. Find your chat_id

1. Send any message to your new bot
2. Visit:  `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Look for `"id"` inside `"chat"` — that number is your chat_id
4. Add it to the config:
   ```json
   "allowed_chat_ids": { "telegram": [123456789], ... }
   ```

### 3c. Register the webhook

```bash
uv run remote.py --register-telegram https://random-words.trycloudflare.com
```

---

## Step 4 — WhatsApp + Messenger (Meta Developer App)

Both platforms share a single Meta Developer app.

### 4a. Create the Meta app

1. Go to [developers.facebook.com](https://developers.facebook.com) → **My Apps** → **Create App**
2. Choose **Other** → **Business** → name it (e.g. "SysControl")
3. In the app dashboard, add two products: **WhatsApp** and **Messenger**

---

## Step 5 — WhatsApp Cloud API

### 5a. Connect your phone number

1. In the Meta Developer Console → **WhatsApp** → **Getting Started**
2. Click **Add phone number** → enter your mobile number → verify via SMS
3. Copy the **Phone Number ID** from the panel (looks like `1234567890123456`)
4. Generate a **System User Token** (Settings → Business Settings → System Users → Add → Admin → Generate token → select WhatsApp app with `whatsapp_business_messaging` permission)
5. Fill in config:
   ```json
   "whatsapp": {
     "enabled": true,
     "phone_number_id": "1234567890123456",
     "access_token": "EAAxxxxxxxx...",
     "verify_token": "syscontrol_wh_verify"
   }
   ```

### 5b. Register webhook

1. In the Meta Console → **WhatsApp** → **Configuration** → **Webhook** → **Edit**
2. **Callback URL**: `https://random-words.trycloudflare.com/webhook/whatsapp`
3. **Verify token**: `syscontrol_wh_verify` (must match config)
4. Click Verify & Save → subscribe to `messages` field

### 5c. Find your WhatsApp phone number (for allowed_chat_ids)

Your E.164 phone number is used as the chat_id for WhatsApp.

```json
"allowed_chat_ids": { "whatsapp": ["+14155551234"], ... }
```

---

## Step 6 — Messenger

### 6a. Create a Facebook Page (if you don't have one)

Go to [facebook.com/pages/create](https://www.facebook.com/pages/create) — use any name, it's just a relay.

### 6b. Connect Messenger to your app

1. Meta Console → **Messenger** → **Settings** → **Access Tokens** → **Add/Remove Pages** → connect your Page
2. Copy the **Page Access Token**
3. Fill in config:
   ```json
   "messenger": {
     "enabled": true,
     "page_access_token": "EAAxxxxxxxx...",
     "verify_token": "syscontrol_ms_verify"
   }
   ```

### 6c. Register webhook

1. Meta Console → **Messenger** → **Settings** → **Webhooks** → **Add Callback URL**
2. **Callback URL**: `https://random-words.trycloudflare.com/webhook/messenger`
3. **Verify token**: `syscontrol_ms_verify`
4. Subscribe to `messages` field

### 6d. Find your Messenger PSID

Start the bridge (Step 7), send a message to your Page from your Facebook account.
The terminal will log:

```
WARNING  No allowed IDs configured for messenger. Received message from chat_id=1234567890
```

Add that ID to config:
```json
"allowed_chat_ids": { "messenger": ["1234567890"], ... }
```

---

## Step 7 — Start the Bridge

```bash
uv run remote.py
```

Expected output:
```
12:00:00  INFO     Starting MCP server subprocess…
12:00:01  INFO     ✅ Remote bridge ready  |  36 tools  |  platforms: telegram, whatsapp, messenger
```

---

## Step 8 — Test It

Send any of the following from your phone:

```
What's my CPU usage?
Top 5 processes using memory
Set a reminder in 30 minutes to check my build
Is my internet slow?
What Docker containers are running?
When did Time Machine last back up?
```

---

## Running Automatically at Login (macOS)

Create a Launch Agent to start the bridge when your Mac boots:

```bash
cat > ~/Library/LaunchAgents/com.syscontrol.remote.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>       <string>com.syscontrol.remote</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USERNAME/.local/bin/uv</string>
        <string>run</string>
        <string>/path/to/SyscontrolMCP/remote.py</string>
    </array>
    <key>RunAtLoad</key>   <true/>
    <key>KeepAlive</key>   <true/>
    <key>StandardErrorPath</key>  <string>/tmp/syscontrol-remote.log</string>
    <key>StandardOutPath</key>    <string>/tmp/syscontrol-remote.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.syscontrol.remote.plist
```

> Replace `YOUR_USERNAME` and `/path/to/SyscontrolMCP` with real values.
> You still need `cloudflared` running separately — wrap both in a shell script.

---

## Security Notes

- **allowed_chat_ids** is your firewall. Keep it non-empty.
- The config file contains your tokens — ensure `chmod 600 ~/.syscontrol/remote_config.json`
- The Cloudflare Tunnel URL is public; anyone who guesses it can hit the webhooks (but your allowed_chat_ids blocks anything from running the agent)
- For a permanent setup, use a **named** Cloudflare Tunnel (free account) instead of the random-URL tunnel
