#!/usr/bin/env python3
"""
SysControl Remote Bridge
========================
Exposes the SysControl MCP agent to Telegram, WhatsApp (Meta Cloud API),
and Facebook Messenger simultaneously via a single FastAPI webhook server.

Usage
-----
1. Fill in ~/.syscontrol/remote_config.json  (auto-created on first run)
2. Start a Cloudflare Tunnel:  cloudflared tunnel --url http://127.0.0.1:8080
3. Register the Telegram webhook:
       uv run remote.py --register-telegram https://<tunnel-url>
4. Add each platform's webhook URL in the Meta Developer Console:
       WhatsApp:  https://<tunnel-url>/webhook/whatsapp
       Messenger: https://<tunnel-url>/webhook/messenger
5. Start the bridge:  uv run remote.py
"""

import json
import logging
import sys
import threading
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from openai import OpenAI

# ── Shared utilities from agent/core.py ──────────────────────────────────────
from agent.core import (
    MCPClient,
    MCPClientPool,
    load_system_prompt,
    mcp_to_openai_tools,
)

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger("syscontrol-remote")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)

# ── Constants ─────────────────────────────────────────────────────────────────
CONFIG_PATH  = Path.home() / ".syscontrol" / "remote_config.json"
MAX_TOKENS   = 16384
POOL_SIZE    = 2       # lighter footprint than the CLI; tools still run in parallel
MAX_HISTORY  = 40      # messages kept per conversation before oldest are trimmed

_CONFIG_TEMPLATE = {
    "provider":    "local",
    "model":       "qwen2.5",
    "api_key":     "ollama",
    "base_url":    "http://localhost:11434/v1",
    "max_history": MAX_HISTORY,
    "allowed_chat_ids": {
        "telegram":  [],   # Telegram chat_ids (integers)   e.g. [123456789]
        "whatsapp":  [],   # Phone numbers in E.164 format   e.g. ["+14155551234"]
        "messenger": [],   # Messenger PSIDs (strings)        e.g. ["1234567890"]
    },
    "telegram": {
        "enabled": True,
        "token":   "YOUR_BOT_TOKEN",         # from @BotFather
    },
    "whatsapp": {
        "enabled":         True,
        "phone_number_id": "YOUR_PHONE_NUMBER_ID",   # Meta Developer Console
        "access_token":    "YOUR_ACCESS_TOKEN",       # System user token
        "verify_token":    "syscontrol_wh_verify",   # any secret string you choose
    },
    "messenger": {
        "enabled":            True,
        "page_access_token":  "YOUR_PAGE_ACCESS_TOKEN",  # Meta Developer Console
        "verify_token":       "syscontrol_ms_verify",    # any secret string you choose
    },
}

# ── Config ────────────────────────────────────────────────────────────────────

def _ensure_config() -> None:
    """Create the config template on first run and exit so the user can fill it in.
    Must be called from main() BEFORE uvicorn starts — safe to sys.exit() there.
    """
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(_CONFIG_TEMPLATE, indent=2))
        print(f"\n✅ Config template created at:\n   {CONFIG_PATH}\n")
        print("Fill in your tokens/keys, then re-run  uv run remote.py")
        sys.exit(0)


def load_config() -> dict:
    """Load the config file. Assumes it already exists (_ensure_config was called)."""
    return json.loads(CONFIG_PATH.read_text())


# ── Session management ────────────────────────────────────────────────────────
# Each (platform, chat_id) pair gets its own message history list.
# Access is protected by _session_lock.

_sessions: dict[tuple[str, str], list[dict]] = {}
_session_lock = threading.Lock()


def get_session(platform: str, chat_id: str) -> list[dict]:
    key = (platform, chat_id)
    with _session_lock:
        if key not in _sessions:
            _sessions[key] = []
        return _sessions[key]


def trim_session(session: list[dict], max_msgs: int) -> None:
    """Trim *session* in-place to at most *max_msgs* recent messages."""
    with _session_lock:
        if len(session) > max_msgs:
            del session[:len(session) - max_msgs]


# ── Outbound HTTP (sync — called from daemon threads) ─────────────────────────

_http = httpx.Client(timeout=30)


def _post(url: str, *, headers: dict | None = None, params: dict | None = None,
          payload: dict) -> httpx.Response:
    return _http.post(url, headers=headers or {}, params=params or {}, json=payload)


def _telegram_send(chat_id: int | str, text: str, token: str) -> None:
    """Send a Telegram message with one retry on transient failures."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4096]}
    for attempt in range(2):
        try:
            _post(url, payload=payload)
            return
        except Exception as exc:
            if attempt == 0:
                log.warning("Telegram send failed (%s), retrying once…", exc)
            else:
                log.error("Telegram send failed after retry: %s", exc)


def _whatsapp_send(phone: str, text: str, cfg: dict) -> None:
    _post(
        f"https://graph.facebook.com/v21.0/{cfg['phone_number_id']}/messages",
        headers={"Authorization": f"Bearer {cfg['access_token']}"},
        payload={
            "messaging_product": "whatsapp",
            "to":   phone,
            "type": "text",
            "text": {"body": text[:4096]},
        },
    )


def _messenger_send(psid: str, text: str, token: str) -> None:
    _post(
        "https://graph.facebook.com/v21.0/me/messages",
        params={"access_token": token},
        payload={
            "recipient": {"id": psid},
            "message":   {"text": text[:2000]},
        },
    )


# ── Core agent runner ─────────────────────────────────────────────────────────
# This mirrors run_turn() from agent/cli.py but captures output as a string
# instead of printing, and uses non-streaming for simpler thread safety.

def run_agent(
    user_text: str,
    session:   list[dict],
    pool:      MCPClientPool,
    tools:     list[dict],
    system_msg: dict,
    model:     str,
    client:    OpenAI,
    max_history: int,
) -> str:
    """Run one remote turn and return the response text."""
    session.append({"role": "user", "content": user_text})
    trim_session(session, max_history)

    response_parts: list[str] = []

    while True:
        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            tools=tools or [],
            messages=[system_msg] + session,
            stream=False,
        )
        choice  = response.choices[0]
        msg     = choice.message
        content = msg.content or ""
        finish  = choice.finish_reason

        if finish == "tool_calls" and msg.tool_calls:
            # Record assistant turn with tool call metadata
            session.append({
                "role":    "assistant",
                "content": content or None,
                "tool_calls": [
                    {
                        "id":   tc.id,
                        "type": "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Build the list for the pool
            tool_dicts = [
                {
                    "id": tc.id,
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
            names = [tc.function.name for tc in msg.tool_calls]
            log.info("Tool calls: %s", ", ".join(names))

            # Execute in parallel via pool
            results = pool.call_tools_parallel(tool_dicts)
            for tc_id, _name, result in results:
                session.append({
                    "role":        "tool",
                    "tool_call_id": tc_id,
                    "content":     result,
                })

            # Surface tool names used (helpful context in the reply)
            response_parts.append(f"⚙ {', '.join(names)}")

        else:
            session.append({"role": "assistant", "content": content})
            if content:
                response_parts.append(content)
            break

    return "\n".join(response_parts) or "✅ Done."


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(application: FastAPI):
    global _cfg, _pool, _tools, _sysmsg, _client

    _cfg = load_config()

    log.info("Starting MCP server subprocess…")
    primary = MCPClient()
    _pool   = MCPClientPool(primary, pool_size=POOL_SIZE)

    mcp_tools = primary.list_tools()
    _tools    = mcp_to_openai_tools(mcp_tools)
    _sysmsg   = {"role": "system", "content": load_system_prompt()}
    _client   = OpenAI(
        api_key=_cfg.get("api_key", "ollama") or "ollama",
        base_url=_cfg.get("base_url", "http://localhost:11434/v1"),
    )

    enabled = [p for p in ("telegram", "whatsapp", "messenger")
               if _cfg.get(p, {}).get("enabled")]
    log.info(
        "✅ Remote bridge ready  |  %d tools  |  platforms: %s",
        len(_tools), ", ".join(enabled) or "none",
    )

    yield   # server runs here

    if _pool:
        _pool.close_all()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="SysControl Remote Bridge",
    docs_url=None,
    redoc_url=None,
    lifespan=_lifespan,
)

# Global state — populated at startup
_cfg:     dict         = {}
_pool:    MCPClientPool | None = None
_tools:   list[dict]   = []
_sysmsg:  dict         = {}
_client:  OpenAI | None = None


def _is_allowed(platform: str, chat_id: str) -> bool:
    allowed = _cfg.get("allowed_chat_ids", {}).get(platform, [])
    if not allowed:
        # Allow-list is empty → reject all messages and log the sender so the
        # user can copy the ID into their config.  Accepting everyone when the
        # list is missing would make the bot publicly accessible.
        log.warning(
            "⚠  No allowed IDs configured for %s — rejecting chat_id=%s. "
            "Add this ID to allowed_chat_ids in %s to enable access.",
            platform, chat_id, CONFIG_PATH,
        )
        return False
    return str(chat_id) in [str(a) for a in allowed]


def _dispatch(platform: str, chat_id: str, text: str,
              reply_fn: "callable[[str], None]") -> None:
    """Validate, then fire a daemon thread that runs the agent and replies."""
    if not _is_allowed(platform, chat_id):
        reply_fn("⛔ Unauthorized.")
        return

    reply_fn("⏳ Working on it…")

    session = get_session(platform, chat_id)
    max_h   = _cfg.get("max_history", MAX_HISTORY)

    def _work():
        try:
            result = run_agent(
                text, session, _pool, _tools, _sysmsg,
                _cfg["model"], _client, max_h,
            )
            reply_fn(result)
        except Exception as exc:
            log.exception("Agent error on %s/%s", platform, chat_id)
            reply_fn(f"❌ Error: {exc}")

    threading.Thread(target=_work, daemon=True, name=f"agent-{platform}").start()


# ── Telegram ──────────────────────────────────────────────────────────────────

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> dict:
    if not _cfg.get("telegram", {}).get("enabled"):
        return {"ok": True}

    data  = await request.json()
    msg   = data.get("message") or data.get("edited_message")
    if not msg:
        return {"ok": True}

    chat_id = str(msg["chat"]["id"])
    text    = msg.get("text", "").strip()
    if not text:
        return {"ok": True}

    token = _cfg["telegram"]["token"]
    _dispatch("telegram", chat_id, text,
              lambda t: _telegram_send(chat_id, t, token))
    return {"ok": True}


# ── WhatsApp ──────────────────────────────────────────────────────────────────

@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request) -> Response:
    p = request.query_params
    if (p.get("hub.mode") == "subscribe"
            and p.get("hub.verify_token") == _cfg["whatsapp"]["verify_token"]):
        return Response(content=p["hub.challenge"], media_type="text/plain")
    raise HTTPException(status_code=403, detail="WhatsApp verification failed")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> dict:
    if not _cfg.get("whatsapp", {}).get("enabled"):
        return {"ok": True}

    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg.get("type") != "text":
                    continue
                phone = msg["from"]
                text  = msg["text"]["body"].strip()
                wa    = _cfg["whatsapp"]
                _dispatch("whatsapp", phone, text,
                          lambda t, p=phone: _whatsapp_send(p, t, wa))
    return {"ok": True}


# ── Messenger ─────────────────────────────────────────────────────────────────

@app.get("/webhook/messenger")
async def messenger_verify(request: Request) -> Response:
    p = request.query_params
    if (p.get("hub.mode") == "subscribe"
            and p.get("hub.verify_token") == _cfg["messenger"]["verify_token"]):
        return Response(content=p["hub.challenge"], media_type="text/plain")
    raise HTTPException(status_code=403, detail="Messenger verification failed")


@app.post("/webhook/messenger")
async def messenger_webhook(request: Request) -> dict:
    if not _cfg.get("messenger", {}).get("enabled"):
        return {"ok": True}

    data = await request.json()
    if data.get("object") != "page":
        return {"ok": True}

    token = _cfg["messenger"]["page_access_token"]
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" not in event or event["message"].get("is_echo"):
                continue
            psid = event["sender"]["id"]
            text = event["message"].get("text", "").strip()
            if not text:
                continue
            _dispatch("messenger", psid, text,
                      lambda t, p=psid: _messenger_send(p, t, token))
    return {"ok": True}


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {
        "status":    "ok",
        "tools":     len(_tools),
        "platforms": {
            "telegram":  _cfg.get("telegram",  {}).get("enabled", False),
            "whatsapp":  _cfg.get("whatsapp",  {}).get("enabled", False),
            "messenger": _cfg.get("messenger", {}).get("enabled", False),
        },
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _register_telegram(webhook_url: str) -> None:
    """Register (or update) the Telegram bot webhook URL."""
    cfg   = load_config()
    token = cfg.get("telegram", {}).get("token", "")
    if not token or token == "YOUR_BOT_TOKEN":
        sys.exit("❌  Set telegram.token in your config first.")
    url = (
        f"https://api.telegram.org/bot{token}/setWebhook"
        f"?url={webhook_url}/webhook/telegram"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        result = json.loads(r.read().decode())
    if result.get("ok"):
        print(f"✅  Telegram webhook registered → {webhook_url}/webhook/telegram")
    else:
        print(f"❌  Telegram API error: {result}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="SysControl Remote Bridge — Telegram · WhatsApp · Messenger",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port",  type=int, default=8080)
    parser.add_argument("--host",  default="127.0.0.1")
    parser.add_argument(
        "--register-telegram", metavar="TUNNEL_URL",
        help="Register the Telegram webhook with the given public URL, then exit.",
    )
    args = parser.parse_args()

    if args.register_telegram:
        _ensure_config()
        _register_telegram(args.register_telegram.rstrip("/"))
        return

    _ensure_config()   # exits cleanly here if first run — before uvicorn starts
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
