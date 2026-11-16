"""Zero-dependency Discord webhook notification client and environment loader.

Uses Python 3.9 standard library only and hot-loads credentials on every call
from workspace `.env`, global `discord.env`, and process environment variables.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

USER_AGENT = "DiscordBot (https://quotelytics.ca, 1.0)"
DEFAULT_USERNAME = "Antigravity (Quotelytics)"

COLOR_PRESETS: Dict[str, int] = {
    "blurple": 0x5865F2,
    "blue": 0x2563EB,
    "green": 0x16A34A,
    "amber": 0xD97706,
    "red": 0xDC2626,
}

VALID_WEBHOOK_PREFIXES = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
)

CHANNEL_ENV_MAP: Dict[str, str] = {
    "sales": "DISCORD_SALES_WEBHOOK_URL",
    "support": "DISCORD_SUPPORT_WEBHOOK_URL",
    "ops": "DISCORD_OPS_WEBHOOK_URL",
    "default": "DISCORD_WEBHOOK_URL",
}


def _default_env_paths() -> List[str]:
    repo_root = Path(__file__).resolve().parents[4]
    global_env = Path.home() / ".gemini" / "config" / "discord.env"
    return [
        str(global_env),
        str(repo_root / ".env"),
        str(repo_root / ".agents" / "discord_config.json"),
    ]


def _is_placeholder(value: Optional[str]) -> bool:
    if value is None:
        return True
    cleaned = value.strip()
    return not cleaned or cleaned.startswith("ReplaceWith")


def _parse_env_file(path: Path) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return parsed

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return parsed
        if isinstance(data, dict):
            return {
                str(k): str(v)
                for k, v in data.items()
                if isinstance(v, (str, int, float)) and not str(k).startswith("_")
            }
        return parsed

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and (
            (value[0] == '"' and value[-1] == '"')
            or (value[0] == "'" and value[-1] == "'")
        ):
            value = value[1:-1]
        parsed[key] = value
    return parsed


def load_discord_env(env_paths: Optional[List[str]] = None) -> Dict[str, str]:
    """Load Discord credentials from `.env` files and `os.environ`."""
    paths = env_paths if env_paths is not None else _default_env_paths()
    merged: Dict[str, str] = {}

    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            continue
        for key, value in _parse_env_file(path).items():
            if _is_placeholder(value) and not _is_placeholder(merged.get(key)):
                continue
            merged[key] = value

    for key, value in os.environ.items():
        if value and not value.strip().startswith("ReplaceWith"):
            merged[key] = value
        elif key not in merged and value:
            merged[key] = value

    return merged


def resolve_webhook_url(
    channel: str = "default",
    explicit_url: Optional[str] = None,
    env_map: Optional[Dict[str, str]] = None,
) -> str:
    """Resolve and validate the Discord webhook URL for a channel alias."""
    if explicit_url is not None and explicit_url.strip():
        candidate = explicit_url.strip()
        if _is_placeholder(candidate) or not candidate.startswith(VALID_WEBHOOK_PREFIXES):
            raise ValueError(
                "Invalid explicit Discord webhook URL. Expected a URL starting with "
                "'https://discord.com/api/webhooks/' or 'https://discordapp.com/api/webhooks/'."
            )
        return candidate

    env = env_map if env_map is not None else load_discord_env()
    channel_key = (channel or "default").strip().lower().lstrip("#")
    env_var = CHANNEL_ENV_MAP.get(channel_key)
    if env_var is None and channel_key:
        env_var = f"DISCORD_{channel_key.upper()}_WEBHOOK_URL"

    candidate = ""
    if env_var and not _is_placeholder(env.get(env_var)):
        candidate = env[env_var].strip()
    elif not _is_placeholder(env.get("DISCORD_WEBHOOK_URL")):
        candidate = env["DISCORD_WEBHOOK_URL"].strip()

    if not candidate:
        raise ValueError(
            "Discord webhook URL is not configured. Set DISCORD_WEBHOOK_URL "
            "(or channel-specific DISCORD_SALES_WEBHOOK_URL / DISCORD_SUPPORT_WEBHOOK_URL / "
            "DISCORD_OPS_WEBHOOK_URL) in '.agents/discord_config.json', '.env', or "
            "'~/.gemini/config/discord.env'."
        )

    if not candidate.startswith(VALID_WEBHOOK_PREFIXES):
        raise ValueError(
            f"Configured Discord webhook URL for channel '{channel}' is invalid. "
            "Expected a URL starting with 'https://discord.com/api/webhooks/' or "
            "'https://discordapp.com/api/webhooks/'."
        )

    return candidate


def parse_color(color_val: Optional[Union[str, int]]) -> int:
    """Parse a Discord embed color from preset names, hex strings, or integers."""
    if color_val is None:
        return COLOR_PRESETS["blurple"]
    if isinstance(color_val, int):
        return max(0, min(0xFFFFFF, color_val))

    cleaned = str(color_val).strip().lower()
    if not cleaned:
        return COLOR_PRESETS["blurple"]
    if cleaned in COLOR_PRESETS:
        return COLOR_PRESETS[cleaned]
    if cleaned.startswith("#"):
        try:
            return max(0, min(0xFFFFFF, int(cleaned[1:], 16)))
        except ValueError:
            return COLOR_PRESETS["blurple"]
    if cleaned.startswith("0x"):
        try:
            return max(0, min(0xFFFFFF, int(cleaned, 16)))
        except ValueError:
            return COLOR_PRESETS["blurple"]
    try:
        return max(0, min(0xFFFFFF, int(cleaned, 10)))
    except ValueError:
        try:
            return max(0, min(0xFFFFFF, int(cleaned, 16)))
        except ValueError:
            return COLOR_PRESETS["blurple"]


def build_webhook_payload(
    content: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[str] = "blurple",
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    footer: Optional[str] = None,
    username: str = DEFAULT_USERNAME,
) -> Dict[str, Any]:
    """Construct a valid Discord webhook JSON payload."""
    payload: Dict[str, Any] = {}
    if username:
        payload["username"] = username
    if content:
        payload["content"] = str(content)[:2000]

    has_embed = any(
        item is not None and item != [] and item != ""
        for item in (title, description, fields, footer)
    )
    if has_embed:
        embed: Dict[str, Any] = {"color": parse_color(color)}
        if title:
            embed["title"] = str(title)[:256]
        if description:
            embed["description"] = str(description)[:4096]
        if fields:
            normalized_fields: List[Dict[str, Any]] = []
            for item in fields[:25]:
                if len(item) == 2:
                    name, value = item  # type: ignore[misc]
                    inline = False
                else:
                    name, value, inline = item[:3]
                normalized_fields.append(
                    {
                        "name": str(name)[:256] or "\u200b",
                        "value": str(value)[:1024] or "\u200b",
                        "inline": bool(inline),
                    }
                )
            embed["fields"] = normalized_fields
        if footer:
            embed["footer"] = {"text": str(footer)[:2048]}
        payload["embeds"] = [embed]

    return payload


def _build_multipart_body(
    payload: Dict[str, Any], file_path: str
) -> Tuple[bytes, str]:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Attachment file not found: {file_path}")

    file_bytes = path.read_bytes()
    filename = path.name
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    boundary = f"----AntigravityDiscord{uuid.uuid4().hex}"

    parts: List[bytes] = []
    parts.append(
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="payload_json"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode("utf-8")
        + json.dumps(payload).encode("utf-8")
        + b"\r\n"
    )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        + file_bytes
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))

    content_type = f"multipart/form-data; boundary={boundary}"
    return b"".join(parts), content_type


def _default_http_transport(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[bytes] = None,
) -> Tuple[int, str]:
    req = urllib.request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read().decode("utf-8", errors="replace")
            return status, raw
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Discord HTTP {exc.code} {exc.reason}: {err_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Discord network error: {exc.reason}") from exc


def _normalize_transport_result(result: Any) -> Tuple[int, Any]:
    if isinstance(result, tuple) and len(result) == 2:
        status, raw = result
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped:
                try:
                    return int(status), json.loads(stripped)
                except json.JSONDecodeError:
                    return int(status), raw
            return int(status), {}
        return int(status), raw
    if isinstance(result, dict):
        return int(result.get("status", 200)), result
    return 200, result


def send_discord_webhook(
    content: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[str] = "blurple",
    fields: Optional[List[Tuple[str, str, bool]]] = None,
    footer: Optional[str] = None,
    username: str = DEFAULT_USERNAME,
    channel: str = "default",
    webhook_url: Optional[str] = None,
    file_path: Optional[str] = None,
    dry_run: bool = False,
    http_transport: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Send a message, embed, or file attachment to a Discord Incoming Webhook."""
    if not any(
        item is not None and item != [] and item != ""
        for item in (content, title, description, fields, footer, file_path)
    ):
        raise ValueError(
            "Provide at least one of content, title, description, fields, footer, or file_path."
        )

    payload = build_webhook_payload(
        content=content,
        title=title,
        description=description,
        color=color,
        fields=fields,
        footer=footer,
        username=username,
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "channel": channel,
            "payload": payload,
            "file_path": file_path,
        }

    resolved_url = resolve_webhook_url(channel=channel, explicit_url=webhook_url)
    separator = "&" if "?" in resolved_url else "?"
    request_url = (
        resolved_url
        if "wait=" in resolved_url
        else f"{resolved_url}{separator}wait=true"
    )

    headers: Dict[str, str] = {"User-Agent": USER_AGENT}
    if file_path:
        body_bytes, content_type = _build_multipart_body(payload, file_path)
        headers["Content-Type"] = content_type
    else:
        body_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    transport = http_transport or _default_http_transport
    raw_result = transport(
        method="POST",
        url=request_url,
        headers=headers,
        body=body_bytes,
    )
    status_code, parsed = _normalize_transport_result(raw_result)

    response: Dict[str, Any] = {
        "ok": 200 <= status_code < 300,
        "status": status_code,
        "channel": channel,
        "message": parsed,
    }
    if isinstance(parsed, dict):
        if "id" in parsed:
            response["message_id"] = parsed["id"]
        if "channel_id" in parsed:
            response["channel_id"] = parsed["channel_id"]
    return response


def _parse_cli_field(raw: str) -> Tuple[str, str, bool]:
    if "=" not in raw:
        raise ValueError(f"Invalid --field '{raw}'. Expected format 'Name=Value'.")
    name, value = raw.split("=", 1)
    inline = False
    if value.endswith("|inline"):
        value = value[: -len("|inline")]
        inline = True
    return name.strip(), value.strip(), inline


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send a Discord webhook notification, rich embed, or file attachment."
    )
    parser.add_argument("--message", "-m", dest="content", help="Plain message content")
    parser.add_argument("--title", help="Embed title")
    parser.add_argument("--description", help="Embed description")
    parser.add_argument(
        "--color",
        default="blurple",
        help="Embed color preset (blurple, blue, green, amber, red) or hex (#5865F2)",
    )
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        help="Embed field in 'Name=Value' format (repeatable; append '|inline' for inline)",
    )
    parser.add_argument("--footer", help="Embed footer text")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="Webhook display name")
    parser.add_argument(
        "--channel",
        default="default",
        help="Channel alias: default, sales, support, ops",
    )
    parser.add_argument("--webhook-url", help="Explicit Discord webhook URL override")
    parser.add_argument("--file", dest="file_path", help="Path to a file to attach")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print payload without sending a network request",
    )

    args = parser.parse_args(argv)
    try:
        parsed_fields = [_parse_cli_field(item) for item in args.field] or None
        result = send_discord_webhook(
            content=args.content,
            title=args.title,
            description=args.description,
            color=args.color,
            fields=parsed_fields,
            footer=args.footer,
            username=args.username,
            channel=args.channel,
            webhook_url=args.webhook_url,
            file_path=args.file_path,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
