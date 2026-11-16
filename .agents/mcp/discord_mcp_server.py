"""Zero-dependency Two-Way Discord Bot MCP Server (Stdio JSON-RPC 2.0).

Exposes 7 Discord team collaboration tools over Model Context Protocol (MCP)
using Python 3.9 standard library only, hot-loading credentials from `.env` and
`~/.gemini/config/discord.env` on every call.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "discord-team-ops"
    / "scripts"
)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from discord_notify import (  # noqa: E402
    DEFAULT_USERNAME,
    USER_AGENT,
    _default_http_transport,
    _is_placeholder,
    _normalize_transport_result,
    load_discord_env,
    parse_color,
    send_discord_webhook,
)

DISCORD_API_BASE = "https://discord.com/api/v10"

CHANNEL_TYPE_NAMES: Dict[int, str] = {
    0: "text",
    1: "dm",
    2: "voice",
    3: "group_dm",
    4: "category",
    5: "announcement",
    10: "announcement_thread",
    11: "public_thread",
    12: "private_thread",
    13: "stage",
    15: "forum",
    16: "media",
}

TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "discord_status",
        "description": (
            "Check whether Discord webhooks, bot token, and guild ID are configured in "
            ".env or ~/.gemini/config/discord.env, and verify the live Discord bot connection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "discord_list_channels",
        "description": (
            "List channels in the connected Discord server (auto-discovers guild_id if omitted). "
            "Returns channel IDs, names, types, topics, and parent categories."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "guild_id": {
                    "type": "string",
                    "description": "Optional Discord server (guild) ID override.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "discord_read_messages",
        "description": (
            "Read recent messages from a Discord text channel or thread in chronological order."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel or thread ID.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of messages to return (1-100, default 20).",
                    "default": 20,
                },
            },
            "required": ["channel_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "discord_send_message",
        "description": (
            "Send a message, reply, or rich embed directly into a Discord channel or thread using the Bot API."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Target Discord channel or thread ID.",
                },
                "content": {
                    "type": "string",
                    "description": "Plain text / markdown message body (up to 2000 chars).",
                },
                "reply_to_message_id": {
                    "type": "string",
                    "description": "Optional message ID to reply to cleanly inline.",
                },
                "embed_title": {
                    "type": "string",
                    "description": "Optional rich embed title.",
                },
                "embed_description": {
                    "type": "string",
                    "description": "Optional rich embed description.",
                },
                "embed_color": {
                    "type": "string",
                    "description": "Optional embed color preset (blurple, blue, green, amber, red) or hex.",
                    "default": "blurple",
                },
            },
            "required": ["channel_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "discord_create_thread",
        "description": (
            "Create a Discord thread in a channel (either attached to an existing message or standalone), "
            "optionally posting an opening message inside the new thread."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Parent Discord text channel ID.",
                },
                "name": {
                    "type": "string",
                    "description": "Thread title (1-100 characters).",
                },
                "message_id": {
                    "type": "string",
                    "description": "Optional existing message ID to start the thread from.",
                },
                "auto_archive_duration": {
                    "type": "integer",
                    "description": "Minutes of inactivity before archiving (60, 1440, 4320, or 10080).",
                    "default": 1440,
                },
                "content": {
                    "type": "string",
                    "description": "Optional opening message to post inside the newly created thread.",
                },
            },
            "required": ["channel_id", "name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "discord_search_messages",
        "description": (
            "Search recent messages in a Discord channel by text query (matches content and embeds) "
            "and optional author filter."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel or thread ID to search.",
                },
                "query": {
                    "type": "string",
                    "description": "Case-insensitive keyword or phrase to search for.",
                },
                "author": {
                    "type": "string",
                    "description": "Optional case-insensitive author username or display name filter.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many recent messages to scan (1-100, default 50).",
                    "default": 50,
                },
            },
            "required": ["channel_id", "query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "discord_send_webhook",
        "description": (
            "Post a formatted notification, rich embed card, or file attachment via a Discord Incoming Webhook "
            "(supports channel aliases: default, sales, support, ops)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Plain text message content."},
                "title": {"type": "string", "description": "Rich embed card title."},
                "description": {"type": "string", "description": "Rich embed card description."},
                "color": {
                    "type": "string",
                    "description": "Preset (blurple, blue, green, amber, red) or hex color.",
                    "default": "blurple",
                },
                "fields": {
                    "type": "array",
                    "description": "Optional list of embed fields ({name, value, inline}).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                            "inline": {"type": "boolean", "default": False},
                        },
                        "required": ["name", "value"],
                    },
                },
                "footer": {"type": "string", "description": "Optional embed footer text."},
                "username": {
                    "type": "string",
                    "description": "Display username override.",
                    "default": DEFAULT_USERNAME,
                },
                "channel": {
                    "type": "string",
                    "description": "Channel alias: default, sales, support, ops.",
                    "default": "default",
                },
                "webhook_url": {
                    "type": "string",
                    "description": "Explicit Discord webhook URL override.",
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional local file path to attach.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate payload without sending to Discord.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
    },
]


def _resolve_bot_token(explicit_token: Optional[str] = None) -> str:
    if explicit_token and not _is_placeholder(explicit_token):
        return explicit_token.strip()
    env = load_discord_env()
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    if _is_placeholder(token):
        raise ValueError(
            "DISCORD_BOT_TOKEN is not configured. Add your Discord Bot Token to "
            "'.agents/discord_config.json', '.env', or 'C:\\Users\\Dylan\\.gemini\\config\\discord.env' "
            "(see DISCORD_SETUP_GUIDE.md)."
        )
    return token


def discord_api_request(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    bot_token: Optional[str] = None,
    http_transport: Optional[Callable[..., Any]] = None,
) -> Any:
    """Execute an authenticated request against the Discord v10 REST API."""
    token = _resolve_bot_token(bot_token)
    clean_path = path if path.startswith("/") else f"/{path}"
    url = f"{DISCORD_API_BASE}{clean_path}"

    headers: Dict[str, str] = {
        "Authorization": f"Bot {token}",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    body_bytes: Optional[bytes] = (
        json.dumps(body).encode("utf-8") if body is not None else None
    )

    transport = http_transport or _default_http_transport
    raw_result = transport(
        method=method.upper(),
        url=url,
        headers=headers,
        body=body_bytes,
    )
    status_code, parsed = _normalize_transport_result(raw_result)
    if status_code >= 400:
        raise RuntimeError(f"Discord API error {status_code}: {parsed}")
    return parsed


def resolve_guild_id(
    explicit_guild_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    http_transport: Optional[Callable[..., Any]] = None,
) -> str:
    """Resolve explicit/env DISCORD_GUILD_ID or auto-discover the bot's first guild."""
    if explicit_guild_id and not _is_placeholder(explicit_guild_id):
        return explicit_guild_id.strip()

    env = load_discord_env()
    configured = env.get("DISCORD_GUILD_ID", "").strip()
    if not _is_placeholder(configured):
        return configured

    guilds = discord_api_request(
        "GET",
        "/users/@me/guilds",
        bot_token=bot_token,
        http_transport=http_transport,
    )
    if not isinstance(guilds, list) or not guilds:
        raise ValueError(
            "Bot is not a member of any Discord server yet, and DISCORD_GUILD_ID is not set. "
            "Invite your bot to your Discord server first."
        )
    return str(guilds[0]["id"])


def _format_channel(raw: Dict[str, Any]) -> Dict[str, Any]:
    raw_type = int(raw.get("type", 0))
    return {
        "id": str(raw.get("id", "")),
        "name": raw.get("name", ""),
        "type": CHANNEL_TYPE_NAMES.get(raw_type, f"type_{raw_type}"),
        "topic": raw.get("topic") or "",
        "parent_id": raw.get("parent_id"),
        "position": raw.get("position", 0),
    }


def _format_message(raw: Dict[str, Any]) -> Dict[str, Any]:
    author_raw = raw.get("author") or {}
    author_name = (
        author_raw.get("global_name")
        or author_raw.get("username")
        or "unknown"
    )
    embeds = [
        {
            "title": e.get("title") or "",
            "description": e.get("description") or "",
        }
        for e in (raw.get("embeds") or [])
    ]
    attachments = [
        {
            "filename": a.get("filename") or "",
            "url": a.get("url") or "",
            "size": a.get("size", 0),
        }
        for a in (raw.get("attachments") or [])
    ]
    return {
        "id": str(raw.get("id", "")),
        "author": author_name,
        "author_username": author_raw.get("username") or "",
        "author_is_bot": bool(author_raw.get("bot", False)),
        "timestamp": raw.get("timestamp") or "",
        "content": raw.get("content") or "",
        "embeds": embeds,
        "attachments": attachments,
    }


def _clamp_limit(val: Any, default: int) -> int:
    try:
        parsed = int(val)
    except (TypeError, ValueError):
        return default
    return max(1, min(100, parsed))


def _handle_discord_status(http_transport: Optional[Callable[..., Any]]) -> Dict[str, Any]:
    env = load_discord_env()
    webhook_ok = not _is_placeholder(env.get("DISCORD_WEBHOOK_URL"))
    sales_ok = not _is_placeholder(env.get("DISCORD_SALES_WEBHOOK_URL"))
    support_ok = not _is_placeholder(env.get("DISCORD_SUPPORT_WEBHOOK_URL"))
    ops_ok = not _is_placeholder(env.get("DISCORD_OPS_WEBHOOK_URL"))
    bot_token_ok = not _is_placeholder(env.get("DISCORD_BOT_TOKEN"))
    guild_id_val = env.get("DISCORD_GUILD_ID", "").strip()
    guild_configured = not _is_placeholder(guild_id_val)

    status: Dict[str, Any] = {
        "ok": True,
        "webhooks": {
            "default_configured": webhook_ok,
            "sales_configured": sales_ok,
            "support_configured": support_ok,
            "ops_configured": ops_ok,
        },
        "bot": {
            "token_configured": bot_token_ok,
            "guild_id_configured": guild_configured,
            "guild_id": guild_id_val if guild_configured else None,
            "connected": False,
        },
        "config_locations": [
            str(Path(__file__).resolve().parents[2] / ".agents" / "discord_config.json"),
            str(Path(__file__).resolve().parents[2] / ".env"),
            str(Path.home() / ".gemini" / "config" / "discord.env"),
        ],
    }

    if not bot_token_ok:
        status["setup_hint"] = (
            "Paste DISCORD_WEBHOOK_URL (for Option 1 notifications) and/or "
            "DISCORD_BOT_TOKEN (for Option 2 two-way channel tools) into "
            "c:\\Users\\Dylan\\Documents\\antigravity\\quick-hertz\\.agents\\discord_config.json "
            "or your project .env."
        )
        return status

    try:
        me = discord_api_request("GET", "/users/@me", http_transport=http_transport)
        guilds = discord_api_request(
            "GET", "/users/@me/guilds", http_transport=http_transport
        )
        status["bot"]["connected"] = True
        status["bot"]["username"] = me.get("username")
        status["bot"]["bot_id"] = me.get("id")
        status["bot"]["guilds"] = [
            {"id": str(g.get("id", "")), "name": g.get("name", "")}
            for g in (guilds or [])
        ]
    except Exception as exc:
        status["bot"]["connected"] = False
        status["bot"]["error"] = str(exc)

    return status


def _handle_list_channels(
    args: Dict[str, Any], http_transport: Optional[Callable[..., Any]]
) -> Dict[str, Any]:
    guild_id = resolve_guild_id(
        explicit_guild_id=args.get("guild_id"),
        http_transport=http_transport,
    )
    raw_channels = discord_api_request(
        "GET",
        f"/guilds/{urllib.parse.quote(guild_id)}/channels",
        http_transport=http_transport,
    )
    formatted = [_format_channel(c) for c in (raw_channels or [])]
    formatted.sort(key=lambda c: (c.get("position", 0), c.get("name", "")))
    return {"ok": True, "guild_id": guild_id, "count": len(formatted), "channels": formatted}


def _handle_read_messages(
    args: Dict[str, Any], http_transport: Optional[Callable[..., Any]]
) -> Dict[str, Any]:
    channel_id = str(args.get("channel_id") or "").strip()
    if not channel_id:
        raise ValueError("channel_id is required.")
    limit = _clamp_limit(args.get("limit"), default=20)
    raw_messages = discord_api_request(
        "GET",
        f"/channels/{urllib.parse.quote(channel_id)}/messages?limit={limit}",
        http_transport=http_transport,
    )
    chronological = [_format_message(m) for m in reversed(raw_messages or [])]
    return {
        "ok": True,
        "channel_id": channel_id,
        "count": len(chronological),
        "messages": chronological,
    }


def _handle_send_message(
    args: Dict[str, Any], http_transport: Optional[Callable[..., Any]]
) -> Dict[str, Any]:
    channel_id = str(args.get("channel_id") or "").strip()
    if not channel_id:
        raise ValueError("channel_id is required.")

    content = args.get("content")
    reply_to = args.get("reply_to_message_id")
    embed_title = args.get("embed_title")
    embed_description = args.get("embed_description")
    embed_color = args.get("embed_color") or "blurple"

    if not any([content, embed_title, embed_description]):
        raise ValueError(
            "Provide at least one of content, embed_title, or embed_description."
        )

    payload: Dict[str, Any] = {}
    if content:
        payload["content"] = str(content)[:2000]
    if reply_to:
        payload["message_reference"] = {"message_id": str(reply_to).strip()}
    if embed_title or embed_description:
        embed: Dict[str, Any] = {"color": parse_color(embed_color)}
        if embed_title:
            embed["title"] = str(embed_title)[:256]
        if embed_description:
            embed["description"] = str(embed_description)[:4096]
        payload["embeds"] = [embed]

    sent = discord_api_request(
        "POST",
        f"/channels/{urllib.parse.quote(channel_id)}/messages",
        body=payload,
        http_transport=http_transport,
    )
    return {"ok": True, "channel_id": channel_id, "message": _format_message(sent)}


def _handle_create_thread(
    args: Dict[str, Any], http_transport: Optional[Callable[..., Any]]
) -> Dict[str, Any]:
    channel_id = str(args.get("channel_id") or "").strip()
    name = str(args.get("name") or "").strip()
    if not channel_id or not name:
        raise ValueError("Both channel_id and name are required.")

    archive_mins = int(args.get("auto_archive_duration") or 1440)
    if archive_mins not in (60, 1440, 4320, 10080):
        archive_mins = 1440

    message_id = str(args.get("message_id") or "").strip()
    if message_id:
        path = (
            f"/channels/{urllib.parse.quote(channel_id)}"
            f"/messages/{urllib.parse.quote(message_id)}/threads"
        )
        body: Dict[str, Any] = {
            "name": name[:100],
            "auto_archive_duration": archive_mins,
        }
    else:
        path = f"/channels/{urllib.parse.quote(channel_id)}/threads"
        body = {
            "name": name[:100],
            "type": 11,
            "auto_archive_duration": archive_mins,
        }

    thread = discord_api_request(
        "POST", path, body=body, http_transport=http_transport
    )
    thread_id = str(thread.get("id", ""))

    opening_message = None
    opening_content = args.get("content")
    if opening_content and thread_id:
        sent = discord_api_request(
            "POST",
            f"/channels/{urllib.parse.quote(thread_id)}/messages",
            body={"content": str(opening_content)[:2000]},
            http_transport=http_transport,
        )
        opening_message = _format_message(sent)

    return {
        "ok": True,
        "thread": {
            "id": thread_id,
            "name": thread.get("name", name),
            "parent_id": thread.get("parent_id", channel_id),
        },
        "opening_message": opening_message,
    }


def _handle_search_messages(
    args: Dict[str, Any], http_transport: Optional[Callable[..., Any]]
) -> Dict[str, Any]:
    channel_id = str(args.get("channel_id") or "").strip()
    query = str(args.get("query") or "").strip()
    if not channel_id or not query:
        raise ValueError("Both channel_id and query are required.")

    author_filter = str(args.get("author") or "").strip().lower()
    limit = _clamp_limit(args.get("limit"), default=50)
    query_lower = query.lower()

    raw_messages = discord_api_request(
        "GET",
        f"/channels/{urllib.parse.quote(channel_id)}/messages?limit={limit}",
        http_transport=http_transport,
    )

    matches: List[Dict[str, Any]] = []
    for raw in reversed(raw_messages or []):
        formatted = _format_message(raw)
        if author_filter:
            haystack_author = (
                f"{formatted['author']} {formatted['author_username']}".lower()
            )
            if author_filter not in haystack_author:
                continue

        searchable_parts = [formatted["content"]]
        for emb in formatted["embeds"]:
            searchable_parts.append(emb.get("title", ""))
            searchable_parts.append(emb.get("description", ""))
        combined_text = "\n".join(searchable_parts).lower()
        if query_lower in combined_text:
            matches.append(formatted)

    return {
        "ok": True,
        "channel_id": channel_id,
        "query": query,
        "scanned": len(raw_messages or []),
        "match_count": len(matches),
        "matches": matches,
    }


def _handle_send_webhook_tool(
    args: Dict[str, Any], http_transport: Optional[Callable[..., Any]]
) -> Dict[str, Any]:
    raw_fields = args.get("fields")
    normalized_fields: Optional[List[Tuple[str, str, bool]]] = None
    if isinstance(raw_fields, list) and raw_fields:
        normalized_fields = []
        for item in raw_fields:
            if isinstance(item, dict):
                normalized_fields.append(
                    (
                        str(item.get("name", "")),
                        str(item.get("value", "")),
                        bool(item.get("inline", False)),
                    )
                )
            elif isinstance(item, str) and "=" in item:
                k, v = item.split("=", 1)
                normalized_fields.append((k.strip(), v.strip(), False))

    return send_discord_webhook(
        content=args.get("content"),
        title=args.get("title"),
        description=args.get("description"),
        color=args.get("color") or "blurple",
        fields=normalized_fields,
        footer=args.get("footer"),
        username=args.get("username") or DEFAULT_USERNAME,
        channel=args.get("channel") or "default",
        webhook_url=args.get("webhook_url"),
        file_path=args.get("file_path"),
        dry_run=bool(args.get("dry_run", False)),
        http_transport=http_transport,
    )


def handle_tool_call(
    name: str,
    arguments: Dict[str, Any],
    http_transport: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Dispatch an MCP tools/call invocation to the corresponding Discord handler."""
    args = arguments or {}
    if name == "discord_status":
        return _handle_discord_status(http_transport=http_transport)
    if name == "discord_list_channels":
        return _handle_list_channels(args, http_transport=http_transport)
    if name == "discord_read_messages":
        return _handle_read_messages(args, http_transport=http_transport)
    if name == "discord_send_message":
        return _handle_send_message(args, http_transport=http_transport)
    if name == "discord_create_thread":
        return _handle_create_thread(args, http_transport=http_transport)
    if name == "discord_search_messages":
        return _handle_search_messages(args, http_transport=http_transport)
    if name == "discord_send_webhook":
        return _handle_send_webhook_tool(args, http_transport=http_transport)
    raise ValueError(f"Unknown Discord MCP tool: {name}")


def handle_jsonrpc_message(
    msg: Dict[str, Any],
    http_transport: Optional[Callable[..., Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Process one JSON-RPC 2.0 MCP message and return the response object (or None for notifications)."""
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if "id" not in msg or req_id is None:
        return None

    if method == "initialize":
        client_proto = params.get("protocolVersion") or "2024-11-05"
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "discord-team-mcp",
                    "version": "1.0.0",
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS_SCHEMA},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            tool_result = handle_tool_call(
                tool_name, tool_args, http_transport=http_transport
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(tool_result, indent=2),
                        }
                    ],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"ok": False, "error": str(exc)}, indent=2
                            ),
                        }
                    ],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}",
        },
    }


def run_stdio_server() -> None:
    """Run the newline-delimited JSON-RPC 2.0 MCP server loop over stdin/stdout."""
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
            continue

        if not isinstance(msg, dict):
            continue

        response = handle_jsonrpc_message(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
