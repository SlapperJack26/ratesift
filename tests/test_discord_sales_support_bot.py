"""Unit tests for the read-only Discord Sales Rep Support Bot."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import discord_sales_support_bot as support_bot  # noqa: E402


@pytest.fixture(scope="module")
def knowledge_index() -> support_bot.ProjectKnowledgeIndex:
    return support_bot.ProjectKnowledgeIndex(repo_root=REPO_ROOT)


def test_read_only_guardrail_blocks_code_edits(
    knowledge_index: support_bot.ProjectKnowledgeIndex,
) -> None:
    blocked_prompts = [
        "please edit main.py and change the starter price to $10",
        "change the code so beta users are free",
        "delete the database table users",
        "drop table invoices",
        "modify the price in code right now",
    ]
    for prompt in blocked_prompts:
        ans = support_bot.answer_sales_rep_question(
            prompt, knowledge_index=knowledge_index
        )
        assert ans["embed_title"] == "Read-Only Sales Support Mode", prompt
        assert ans["embed_color"] == "amber"
        assert ans["attachment_path"] is None

    safe_prompts = [
        "how do we troubleshoot a 403 webhook error?",
        "what is the business tier pricing formula?",
        "how does a customer update their API key?",
    ]
    for prompt in safe_prompts:
        ans = support_bot.answer_sales_rep_question(
            prompt, knowledge_index=knowledge_index
        )
        assert ans["embed_title"] != "Read-Only Sales Support Mode", prompt


def test_curated_sales_topics_matching(
    knowledge_index: support_bot.ProjectKnowledgeIndex,
) -> None:
    pricing = support_bot.answer_sales_rep_question(
        "How is the Business API tier pricing formula calculated?",
        knowledge_index=knowledge_index,
    )
    assert "Pricing Tiers & Business API Formula" in pricing["embed_title"]
    assert "$499" in pricing["embed_description"]
    assert "25,000 quotes/mo" in pricing["embed_description"]

    tabi = support_bot.answer_sales_rep_question(
        "A prospect asked how we compare to Tabi Connect",
        knowledge_index=knowledge_index,
    )
    assert "Tabi Connect" in tabi["embed_title"]
    assert "PIPEDA" in tabi["embed_description"]

    three_pl = support_bot.answer_sales_rep_question(
        "What is a 3PL and how should we pitch them?",
        knowledge_index=knowledge_index,
    )
    assert "3PL" in three_pl["embed_title"]
    assert "POST /api/v1/quotes/batch" in three_pl["embed_description"]

    troubleshoot = support_bot.answer_sales_rep_question(
        "Customer got a 403 and 422 error on the Business API, how do we troubleshoot?",
        knowledge_index=knowledge_index,
    )
    assert "Troubleshooting" in troubleshoot["embed_title"]
    assert "403" in troubleshoot["embed_description"]
    assert "422" in troubleshoot["embed_description"]

    commission = support_bot.answer_sales_rep_question(
        "What is the sales rep commission and equity structure?",
        knowledge_index=knowledge_index,
    )
    assert "Commission" in commission["embed_title"]
    assert "30%" in commission["embed_description"]


def test_document_request_attaches_outreach_file(
    knowledge_index: support_bot.ProjectKnowledgeIndex,
) -> None:
    beta_reply = support_bot.answer_sales_rep_question(
        "can you send me the beta participation agreement",
        knowledge_index=knowledge_index,
    )
    assert beta_reply["attachment_path"] is not None
    assert (
        Path(beta_reply["attachment_path"]).name
        == "11_Beta_Participation_Agreement.docx"
    )
    assert Path(beta_reply["attachment_path"]).is_file()

    setup_reply = support_bot.answer_sales_rep_question(
        "send the sales rep API setup guide",
        knowledge_index=knowledge_index,
    )
    assert setup_reply["attachment_path"] is not None
    assert (
        Path(setup_reply["attachment_path"]).name
        == "11_Sales_Rep_Business_API_Setup_and_Troubleshooting_Guide.docx"
    )
    assert Path(setup_reply["attachment_path"]).is_file()


def test_corpus_search_fallback(
    knowledge_index: support_bot.ProjectKnowledgeIndex,
) -> None:
    cbca_ans = support_bot.answer_sales_rep_question(
        "What does our CBCA articles of incorporation say about directors or share classes?",
        knowledge_index=knowledge_index,
    )
    assert cbca_ans["embed_title"] == "Project Knowledge Answer"
    assert "Source:" in cbca_ans["embed_description"]
    assert "incorporation" in cbca_ans["embed_description"].lower() or "cbca" in cbca_ans["embed_description"].lower()

    casl_ans = support_bot.answer_sales_rep_question(
        "What CASL compliance rules apply to cold email unsubscribe footers?",
        knowledge_index=knowledge_index,
    )
    assert casl_ans["embed_title"] == "Project Knowledge Answer"
    assert "CASL" in casl_ans["embed_description"] or "unsubscribe" in casl_ans["embed_description"].lower()


def test_poll_once_replies_to_new_sales_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    knowledge_index: support_bot.ProjectKnowledgeIndex,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_bot_token_for_poll")
    state_path = tmp_path / "discord_bot_state.json"
    support_bot.save_bot_state(
        {
            "channels": {
                support_bot.SALES_CHANNEL_ID: "100",
                "1570905097238614071": "200",
            }
        },
        state_path=state_path,
    )

    watched = [
        ("sales", support_bot.SALES_CHANNEL_ID, False),
        ("general", "1570905097238614071", True),
    ]

    posted_replies: List[Tuple[str, Dict[str, Any]]] = []

    def mock_transport(
        method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
    ) -> Tuple[int, str]:
        if method == "GET" and f"/channels/{support_bot.SALES_CHANNEL_ID}/messages" in url:
            return 200, json.dumps(
                [
                    {
                        "id": "101",
                        "author": {"username": "other_bot", "bot": True},
                        "content": "Automated webhook notification",
                        "mentions": [],
                    },
                    {
                        "id": "102",
                        "author": {"username": "rep_jane", "bot": False},
                        "content": "What is Tabi Connect and how do we beat them on price?",
                        "mentions": [],
                    },
                ]
            )
        if method == "GET" and "/channels/1570905097238614071/messages" in url:
            return 200, json.dumps(
                [
                    {
                        "id": "201",
                        "author": {"username": "rep_bob", "bot": False},
                        "content": "Good morning everyone, no bot mention here",
                        "mentions": [],
                    }
                ]
            )
        if method == "POST" and "/messages" in url:
            payload = json.loads(body.decode("utf-8")) if body else {}
            posted_replies.append((url, payload))
            return 200, json.dumps({"id": "999", "content": ""})
        raise AssertionError(f"Unexpected call: {method} {url}")

    replies = support_bot.poll_channels_once(
        knowledge_index=knowledge_index,
        state_path=state_path,
        channels=watched,
        http_transport=mock_transport,
    )

    assert replies == 1
    assert len(posted_replies) == 1
    reply_url, reply_payload = posted_replies[0]
    assert f"/channels/{support_bot.SALES_CHANNEL_ID}/messages" in reply_url
    assert reply_payload["message_reference"] == {"message_id": "102"}
    assert "Tabi Connect" in reply_payload["embeds"][0]["title"]

    updated_state = support_bot.load_bot_state(state_path)
    assert updated_state["channels"][support_bot.SALES_CHANNEL_ID] == "102"
    assert updated_state["channels"]["1570905097238614071"] == "201"
