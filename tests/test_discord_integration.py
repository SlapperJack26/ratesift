"""Automated verification tests for Discord webhook skill and two-way MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / ".agents" / "skills" / "discord-team-ops" / "scripts"
MCP_DIR = REPO_ROOT / ".agents" / "mcp"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import discord_mcp_server  # noqa: E402
import discord_notify  # noqa: E402

DISCORD_ENV_KEYS = (
    "DISCORD_WEBHOOK_URL",
    "DISCORD_SALES_WEBHOOK_URL",
    "DISCORD_SUPPORT_WEBHOOK_URL",
    "DISCORD_OPS_WEBHOOK_URL",
    "DISCORD_BOT_TOKEN",
    "DISCORD_GUILD_ID",
)


@pytest.fixture(autouse=True)
def _clean_discord_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in DISCORD_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(discord_notify, "_default_env_paths", lambda: [])


def test_load_discord_env_from_json_and_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "# Comment line\n"
        'DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/111/dotenv_tok"\n'
        "DISCORD_BOT_TOKEN=ReplaceWithDiscordBotToken\n"
        "export DISCORD_GUILD_ID='999888777'\n",
        encoding="utf-8",
    )

    json_file = tmp_path / "discord_config.json"
    json_file.write_text(
        json.dumps(
            {
                "_comment": "ignored",
                "DISCORD_WEBHOOK_URL": "ReplaceWithDiscordWebhookUrl",
                "DISCORD_BOT_TOKEN": "bot.token.from.json",
                "DISCORD_SALES_WEBHOOK_URL": "https://discord.com/api/webhooks/222/sales_tok",
            }
        ),
        encoding="utf-8",
    )

    # Real value from dotenv must NOT be overwritten by ReplaceWith placeholder in JSON,
    # whereas ReplaceWith placeholder in dotenv MUST be replaced by real JSON value.
    env = discord_notify.load_discord_env([str(dotenv_file), str(json_file)])
    assert env["DISCORD_WEBHOOK_URL"] == "https://discord.com/api/webhooks/111/dotenv_tok"
    assert env["DISCORD_BOT_TOKEN"] == "bot.token.from.json"
    assert env["DISCORD_SALES_WEBHOOK_URL"] == "https://discord.com/api/webhooks/222/sales_tok"
    assert env["DISCORD_GUILD_ID"] == "999888777"
    assert "_comment" not in env

    # Process env overrides file values, unless process env is also a placeholder.
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot.token.from.process")
    monkeypatch.setenv("DISCORD_GUILD_ID", "ReplaceWithDiscordServerIdOptional")
    env2 = discord_notify.load_discord_env([str(dotenv_file), str(json_file)])
    assert env2["DISCORD_BOT_TOKEN"] == "bot.token.from.process"
    assert env2["DISCORD_GUILD_ID"] == "999888777"


def test_webhook_dry_run_and_embed_payload() -> None:
    res = discord_notify.send_discord_webhook(
        content="Daily check complete",
        title="Test Alert",
        description="Integration ready",
        color="green",
        fields=[("Mode", "Dry Run", True), ("Tier", "Business", False)],
        footer="Quotelytics Automation",
        channel="ops",
        dry_run=True,
    )

    assert res["ok"] is True
    assert res["dry_run"] is True
    assert res["channel"] == "ops"
    payload = res["payload"]
    assert payload["username"] == discord_notify.DEFAULT_USERNAME
    assert payload["content"] == "Daily check complete"
    embed = payload["embeds"][0]
    assert embed["title"] == "Test Alert"
    assert embed["description"] == "Integration ready"
    assert embed["color"] == discord_notify.COLOR_PRESETS["green"]
    assert embed["fields"] == [
        {"name": "Mode", "value": "Dry Run", "inline": True},
        {"name": "Tier", "value": "Business", "inline": False},
    ]
    assert embed["footer"] == {"text": "Quotelytics Automation"}


def test_webhook_live_transport_and_channel_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DISCORD_SALES_WEBHOOK_URL",
        "https://discord.com/api/webhooks/12345/sales_secret",
    )
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/99999/default_secret",
    )

    captured: List[Dict[str, Any]] = []

    def mock_transport(
        method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
    ) -> Tuple[int, str]:
        captured.append(
            {"method": method, "url": url, "headers": headers, "body": body}
        )
        return 200, json.dumps({"id": "msg_555", "channel_id": "chan_sales"})

    res = discord_notify.send_discord_webhook(
        title="New Business Signup",
        description="Carrier rate sheet uploaded.",
        color="blue",
        channel="sales",
        http_transport=mock_transport,
    )

    assert res["ok"] is True
    assert res["status"] == 200
    assert res["message_id"] == "msg_555"
    assert res["channel_id"] == "chan_sales"
    assert len(captured) == 1

    req = captured[0]
    assert req["method"] == "POST"
    assert req["url"] == "https://discord.com/api/webhooks/12345/sales_secret?wait=true"
    assert req["headers"]["User-Agent"] == "DiscordBot (https://quotelytics.ca, 1.0)"
    assert req["headers"]["Content-Type"] == "application/json"
    decoded = json.loads(req["body"].decode("utf-8"))
    assert decoded["embeds"][0]["color"] == 0x2563EB


def test_webhook_file_upload_multipart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attachment = tmp_path / "rate_summary.txt"
    attachment.write_text("TOR -> VAN: $1,250 CAD", encoding="utf-8")

    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/99999/default_secret",
    )

    captured: Dict[str, Any] = {}

    def mock_transport(
        method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
    ) -> Tuple[int, str]:
        captured.update({"url": url, "headers": headers, "body": body})
        return 200, json.dumps({"id": "msg_file_1", "channel_id": "chan_1"})

    res = discord_notify.send_discord_webhook(
        content="Here is the rate summary:",
        file_path=str(attachment),
        http_transport=mock_transport,
    )

    assert res["ok"] is True
    ctype = captured["headers"]["Content-Type"]
    assert ctype.startswith("multipart/form-data; boundary=----AntigravityDiscord")
    raw_body = captured["body"]
    assert b'name="payload_json"' in raw_body
    assert b'name="files[0]"; filename="rate_summary.txt"' in raw_body
    assert b"TOR -> VAN: $1,250 CAD" in raw_body


def test_mcp_initialize_and_tools_list() -> None:
    init_resp = discord_mcp_server.handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert init_resp is not None
    assert init_resp["id"] == 1
    assert init_resp["result"]["protocolVersion"] == "2024-11-05"
    assert init_resp["result"]["serverInfo"]["name"] == "discord-team-mcp"

    notif_resp = discord_mcp_server.handle_jsonrpc_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert notif_resp is None

    list_resp = discord_mcp_server.handle_jsonrpc_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    assert list_resp is not None
    tool_names = {t["name"] for t in list_resp["result"]["tools"]}
    assert tool_names == {
        "discord_status",
        "discord_list_channels",
        "discord_read_messages",
        "discord_send_message",
        "discord_create_thread",
        "discord_search_messages",
        "discord_send_webhook",
    }


def test_mcp_status_unconfigured_and_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point load_discord_env to an empty file so local workspace config does not interfere.
    empty_env = tmp_path / "empty_config.json"
    empty_env.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        discord_notify, "_default_env_paths", lambda: [str(empty_env)]
    )

    unconf_resp = discord_mcp_server.handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "discord_status", "arguments": {}},
        }
    )
    assert unconf_resp is not None
    assert unconf_resp["result"]["isError"] is False
    unconf_data = json.loads(unconf_resp["result"]["content"][0]["text"])
    assert unconf_data["bot"]["token_configured"] is False
    assert unconf_data["webhooks"]["default_configured"] is False
    assert "discord_config.json" in unconf_data["setup_hint"]

    # Now configure Bot Token & Default Webhook
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_bot_token_123")
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/777/tok",
    )

    def mock_transport(
        method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
    ) -> Tuple[int, str]:
        assert headers["Authorization"] == "Bot test_bot_token_123"
        assert headers["User-Agent"] == "DiscordBot (https://quotelytics.ca, 1.0)"
        if url.endswith("/users/@me"):
            return 200, json.dumps({"id": "bot_1", "username": "QuotelyticsBot"})
        if url.endswith("/users/@me/guilds"):
            return 200, json.dumps([{"id": "guild_42", "name": "Quotelytics Team"}])
        raise AssertionError(f"Unexpected URL: {url}")

    conf_resp = discord_mcp_server.handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "discord_status", "arguments": {}},
        },
        http_transport=mock_transport,
    )
    assert conf_resp is not None
    conf_data = json.loads(conf_resp["result"]["content"][0]["text"])
    assert conf_data["webhooks"]["default_configured"] is True
    assert conf_data["bot"]["token_configured"] is True
    assert conf_data["bot"]["connected"] is True
    assert conf_data["bot"]["username"] == "QuotelyticsBot"
    assert conf_data["bot"]["guilds"] == [{"id": "guild_42", "name": "Quotelytics Team"}]


def test_mcp_two_way_channel_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot_secret_abc")
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/888/hook_abc",
    )

    calls: List[Tuple[str, str, Any]] = []

    def mock_transport(
        method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
    ) -> Tuple[int, str]:
        parsed_body = json.loads(body.decode("utf-8")) if body else None
        calls.append((method, url, parsed_body))

        if method == "GET" and url.endswith("/users/@me/guilds"):
            return 200, json.dumps([{"id": "guild_99", "name": "Sales Team"}])
        if method == "GET" and url.endswith("/guilds/guild_99/channels"):
            return 200, json.dumps(
                [
                    {"id": "ch_2", "name": "support", "type": 0, "position": 2},
                    {"id": "ch_1", "name": "sales-onboarding", "type": 0, "position": 1, "topic": "API help"},
                ]
            )
        if method == "GET" and "/channels/ch_1/messages?limit=" in url:
            return 200, json.dumps(
                [
                    {
                        "id": "m_2",
                        "author": {"username": "rep_alex", "global_name": "Alex"},
                        "timestamp": "2026-11-13T15:05:00Z",
                        "content": "Customer got 403 on webhook URL test",
                        "embeds": [],
                        "attachments": [],
                    },
                    {
                        "id": "m_1",
                        "author": {"username": "rep_sam", "global_name": "Sam"},
                        "timestamp": "2026-11-13T15:00:00Z",
                        "content": "Morning team! Any updates on Tabi Connect?",
                        "embeds": [{"title": "Tabi Note", "description": "Pricing comparison"}],
                        "attachments": [],
                    },
                ]
            )
        if method == "POST" and url.endswith("/channels/ch_1/messages"):
            return 200, json.dumps(
                {
                    "id": "m_3",
                    "author": {"username": "QuotelyticsBot", "bot": True},
                    "timestamp": "2026-11-13T15:06:00Z",
                    "content": parsed_body["content"],
                }
            )
        if method == "POST" and url.endswith("/channels/ch_1/messages/m_2/threads"):
            return 200, json.dumps(
                {"id": "th_1", "name": parsed_body["name"], "parent_id": "ch_1"}
            )
        if method == "POST" and url.endswith("/channels/th_1/messages"):
            return 200, json.dumps(
                {
                    "id": "m_4",
                    "author": {"username": "QuotelyticsBot", "bot": True},
                    "timestamp": "2026-11-13T15:07:00Z",
                    "content": parsed_body["content"],
                }
            )
        if method == "POST" and url.startswith("https://discord.com/api/webhooks/888/hook_abc"):
            return 200, json.dumps({"id": "wh_msg_1", "channel_id": "ch_1"})

        raise AssertionError(f"Unexpected call: {method} {url}")

    # 1. List channels (auto-discovers guild_99)
    ch_res = discord_mcp_server.handle_tool_call(
        "discord_list_channels", {}, http_transport=mock_transport
    )
    assert ch_res["guild_id"] == "guild_99"
    assert [c["name"] for c in ch_res["channels"]] == ["sales-onboarding", "support"]

    # 2. Read messages (chronological order: m_1 then m_2)
    read_res = discord_mcp_server.handle_tool_call(
        "discord_read_messages",
        {"channel_id": "ch_1", "limit": 10},
        http_transport=mock_transport,
    )
    assert [m["id"] for m in read_res["messages"]] == ["m_1", "m_2"]
    assert read_res["messages"][0]["author"] == "Sam"

    # 3. Send reply referencing m_2
    send_res = discord_mcp_server.handle_tool_call(
        "discord_send_message",
        {
            "channel_id": "ch_1",
            "content": "Have them use an HTTPS URL for their webhook!",
            "reply_to_message_id": "m_2",
        },
        http_transport=mock_transport,
    )
    assert send_res["message"]["id"] == "m_3"
    post_payload = next(
        body for m, u, body in calls if m == "POST" and u.endswith("/channels/ch_1/messages")
    )
    assert post_payload["message_reference"] == {"message_id": "m_2"}

    # 4. Create thread attached to m_2 with opening message
    thread_res = discord_mcp_server.handle_tool_call(
        "discord_create_thread",
        {
            "channel_id": "ch_1",
            "name": "Webhook 403 Triage",
            "message_id": "m_2",
            "content": "Checking SSRF & HTTPS requirements...",
        },
        http_transport=mock_transport,
    )
    assert thread_res["thread"]["id"] == "th_1"
    assert thread_res["opening_message"]["id"] == "m_4"

    # 5. Search messages across content and embeds
    search_res = discord_mcp_server.handle_tool_call(
        "discord_search_messages",
        {"channel_id": "ch_1", "query": "tabi", "author": "sam"},
        http_transport=mock_transport,
    )
    assert search_res["match_count"] == 1
    assert search_res["matches"][0]["id"] == "m_1"

    # 6. Send webhook via MCP tool
    wh_res = discord_mcp_server.handle_tool_call(
        "discord_send_webhook",
        {
            "title": "Onboarding Done",
            "description": "Account ready",
            "color": "green",
            "fields": [{"name": "Customer", "value": "Acme 3PL", "inline": True}],
        },
        http_transport=mock_transport,
    )
    assert wh_res["ok"] is True
    assert wh_res["message_id"] == "wh_msg_1"
