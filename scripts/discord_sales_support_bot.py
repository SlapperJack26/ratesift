"""Read-only 24/7 Discord Sales Rep Support Bot for Quotelytics.

Watches `#sales` (every non-bot question) and `@Antigravity` mentions in other
project channels, answering questions from curated Quotelytics sales playbooks
and a live-indexed search corpus of workspace outreach, onboarding, legal, and
technical documentation. Strictly read-only: refuses code/DB edits.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / ".agents" / "skills" / "discord-team-ops" / "scripts"
MCP_DIR = REPO_ROOT / ".agents" / "mcp"

for _path in (str(SCRIPTS_DIR), str(MCP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from discord_mcp_server import (  # noqa: E402
    DISCORD_API_BASE,
    _resolve_bot_token,
    discord_api_request,
)
from discord_notify import (  # noqa: E402
    USER_AGENT,
    _build_multipart_body,
    _default_http_transport,
    _normalize_transport_result,
    parse_color,
)

BOT_USER_ID = "1570906237388857394"
SALES_CHANNEL_ID = "1570905200808431785"
WATCHED_CHANNELS: List[Tuple[str, str, bool]] = [
    ("sales", SALES_CHANNEL_ID, False),
    ("general", "1570905097238614071", True),
    ("beta-docs", "1570905157879734393", True),
    ("incorporate", "1570905181615427716", True),
]
DEFAULT_STATE_PATH = REPO_ROOT / ".agents" / "discord_bot_state.json"

BRAIN_PLAYBOOK_PATH = Path(
    r"C:\Users\Dylan\.gemini\antigravity\brain\ec698020-a512-4f06-ab67-4069143a572d\sales_rep_onboarding_playbook.md"
)

STOPWORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "do", "does", "for", "from", "get", "give", "have", "he", "help", "here",
    "how", "i", "if", "in", "into", "is", "it", "its", "me", "my", "no", "not",
    "of", "on", "or", "our", "out", "please", "project", "say", "see", "she",
    "so", "some", "tell", "that", "the", "their", "them", "there", "these",
    "they", "this", "to", "up", "us", "was", "we", "were", "what", "when",
    "where", "which", "who", "why", "will", "with", "would", "you", "your",
    "antigravity", "quotelytics", "about", "explain", "send", "question",
}

_MODIFICATION_VERB_RE = re.compile(
    r"\b(edit|modify|change|update|delete|drop|alter|rewrite|patch|remove|"
    r"overwrite|truncate|refactor|commit|push|deploy|restart|hack|bypass)\b",
    re.IGNORECASE,
)
_MODIFICATION_TARGET_RE = re.compile(
    r"(main\.py|\w+\.(?:py|html|js|css|json|sql|db|bat)\b|"
    r"\b(?:the code|source code|codebase|database|db|table|tables|schema|"
    r"users table|server files|backend|frontend|repo|repository|"
    r"price in code|pricing in code|subscription price in|config\.json)\b)",
    re.IGNORECASE,
)

_ATTACHMENT_INTENT_RE = re.compile(
    r"\b(send|attach|upload|share|download|give me|copy of|word doc|"
    r"docx|xlsx|csv|spreadsheet|file|document)\b",
    re.IGNORECASE,
)


def is_code_modification_request(text: str) -> bool:
    """Return True if the message asks to modify code, database, or server files."""
    if not text:
        return False
    cleaned = re.sub(r"<@!?\d+>", "", text).strip()
    if re.search(
        r"\b(edit\s+main\.py|change\s+the\s+code|delete\s+the\s+database|"
        r"drop\s+table|modify\s+the\s+price\s+in\s+code)\b",
        cleaned,
        re.IGNORECASE,
    ):
        return True
    return bool(
        _MODIFICATION_VERB_RE.search(cleaned)
        and _MODIFICATION_TARGET_RE.search(cleaned)
    )


CURATED_TOPICS: List[Dict[str, Any]] = [
    {
        "id": "troubleshooting",
        "title": "Business API Troubleshooting & Error Codes",
        "color": "amber",
        "attachment_filename": "11_Sales_Rep_Business_API_Setup_and_Troubleshooting_Guide.docx",
        "phrases": {
            "401": 6,
            "402": 6,
            "403": 6,
            "422": 6,
            "429": 6,
            "troubleshoot": 5,
            "troubleshooting": 5,
            "error code": 5,
            "rate limit": 4,
            "payment required": 5,
            "unprocessable": 5,
            "forbidden": 4,
            "unauthorized": 4,
        },
        "keywords": {"error", "failed", "failing", "broken", "fix", "issue", "webhook"},
        "description": (
            "**Quick Fixes for Customer API Issues:**\n"
            "• **`401 Unauthorized`**: Missing `Authorization: Bearer qtl_live_...` header or revoked key → generate a new key in `/console/account#api`.\n"
            "• **`402 Payment Required / Tier Restricted`**: Account is on Starter/Growth/Pro or expired trial → sales rep clicks **Activate Business API** in `/console/admin`.\n"
            "• **`403 Forbidden (Webhook)`**: Webhook URL uses `http://` instead of `https://` or targets a private/local IP (`localhost`, `127.0.0.1`, `10.x`, `192.168.x`).\n"
            "• **`422 Unprocessable Entity`**: Customer has no confirmed quotable rate sheets uploaded yet → upload & confirm ≥ 1 sheet in `/console/sheets`.\n"
            "• **`429 Too Many Requests`**: Exceeded **60 requests/min** per API key → batch up to 50 lanes per call via `POST /api/v1/quotes/batch`."
        ),
    },
    {
        "id": "tabi_connect",
        "title": "Competitor Comparison: Tabi Connect (Hubtek) vs. Quotelytics",
        "color": "blue",
        "attachment_filename": None,
        "phrases": {
            "tabi connect": 8,
            "tabi": 7,
            "hubtek": 7,
            "competitor": 5,
            "vs quotelytics": 5,
        },
        "keywords": {"compare", "comparison", "versus", "alternative", "advantage"},
        "description": (
            "**How Quotelytics Beats Tabi Connect:**\n"
            "• **Pricing:** Tabi Connect typically runs **$150–$500+ USD/mo** (~$210–$700+ CAD/mo) plus custom enterprise setup fees; **Quotelytics** starts at **$79 CAD/mo** self-serve and **$499 CAD/mo** for full Business API + Webhooks.\n"
            "• **Canadian Freight Fit:** Tabi Connect is built around US NMFC freight classes & US cloud hosting. Quotelytics is purpose-built for **Canadian CWT weight breaks, skid/pallet tables, FSA postal routing, and 100% Canadian PIPEDA data residency (WHC Montreal/Halifax)**.\n"
            "• **Speed & Accuracy:** Go live in **5 minutes** with sub-500ms **100% deterministic math** and exact Excel cell provenance (zero AI hallucinations)."
        ),
    },
    {
        "id": "three_pl",
        "title": "3PL Breakdown & How to Pitch 3PL Prospects",
        "color": "blue",
        "attachment_filename": None,
        "phrases": {
            "3pl": 8,
            "third-party logistics": 7,
            "third party logistics": 7,
            "freight forwarder": 5,
        },
        "keywords": {"3pls", "brokerage", "warehousing", "pitch", "qualify"},
        "description": (
            "**3PL Types & Which Quotelytics Tier They Need:**\n"
            "1. **Non-Asset Freight Brokerages:** Match shippers with LTL/FTL carriers across Canada & cross-border.\n"
            "2. **Freight Forwarders:** Coordinate port/air/rail transfers plus domestic Canadian LTL drayage.\n"
            "3. **Integrated Warehousing & Transportation 3PLs:** Handle fulfillment plus multi-carrier LTL shipping.\n\n"
            "**How to Pitch:**\n"
            "• **Manual Excel Quoting (1–20 dispatchers)** → Pitch **Self-Serve ($79–$199 CAD/mo)** to cut 15-min quotes down to <500ms.\n"
            "• **Internal TMS / ERP / Shipper Portal** → Pitch **Business API Tier ($499+ CAD/mo)** with `POST /api/v1/quotes/batch` & HMAC webhooks."
        ),
    },
    {
        "id": "pricing_formula",
        "title": "Quotelytics Pricing Tiers & Business API Formula (CAD)",
        "color": "green",
        "attachment_filename": None,
        "phrases": {
            "business api": 5,
            "business tier": 5,
            "price formula": 7,
            "pricing formula": 7,
            "how much": 5,
            "pricing": 5,
            "starter": 4,
            "growth": 4,
            "pro tier": 4,
            "self-serve": 4,
        },
        "keywords": {"price", "cost", "tier", "tiers", "formula", "monthly", "overage", "carriers"},
        "description": (
            "**Self-Serve Plans (CAD/mo):**\n"
            "• **Brokerage Self-Serve / Growth:** **$79/mo** (Starter **$29/mo**, Pro **$199/mo**) with a **14-day free trial** and **7-day money-back guarantee** on initial charge.\n\n"
            "**Business API Tier Formula (CAD):**\n"
            "`Monthly Price = max($499, min($50 × Carriers, $750) + $300 × Integrations)`\n"
            "• Includes **25,000 quotes/mo**\n"
            "• **Volume Add-Ons:** **+$150/mo** (+25k quotes), **+$450/mo** (+100k quotes), **+$1,500/mo** (+500k quotes), or **$0.008/quote** overage."
        ),
    },
    {
        "id": "api_setup",
        "title": "Zero-Tech Sales Rep Business API Onboarding",
        "color": "blurple",
        "attachment_filename": "11_Sales_Rep_Business_API_Setup_and_Troubleshooting_Guide.docx",
        "phrases": {
            "api setup": 7,
            "business api setup": 8,
            "set up the api": 7,
            "set up api": 7,
            "onboard": 5,
            "onboarding": 5,
            "console/admin": 7,
            "zero-tech": 6,
            "it team": 5,
        },
        "keywords": {"activate", "setup", "customer", "checklist", "enable"},
        "description": (
            "**2-Minute Zero-Tech Onboarding Flow:**\n"
            "1. **Sales Rep (`/console/admin`):** Open `https://quotelytics.ca/console/admin`, search the customer by email, and click **Activate Business API**.\n"
            "2. **Customer (`/console/account#api`):** Customer opens their **Developer API** tab, follows the 3-step readiness checklist, clicks **Verify My API Setup**, and clicks **Copy Email for IT Team**.\n"
            "3. **IT Handoff:** The copied email gives their developers the exact endpoint (`POST /api/v1/quotes/batch`), bearer header, sample payload, and webhook verification info."
        ),
    },
    {
        "id": "commission_equity",
        "title": "Sales Rep Commission, Compensation & Equity",
        "color": "green",
        "attachment_filename": "13_Independent_Sales_Rep_and_Milestone_Equity_Agreement.docx",
        "phrases": {
            "commission": 8,
            "equity": 7,
            "compensation": 7,
            "pay structure": 7,
            "how do reps get paid": 7,
            "sales rep agreement": 7,
        },
        "keywords": {"paid", "payout", "percentage", "vesting", "milestone", "earning"},
        "description": (
            "**Sales Rep Compensation Summary (`13_Independent_Sales_Rep_and_Milestone_Equity_Agreement.docx`):**\n"
            "• **Year 1 Cash Commission:** **30%** recurring commission on Year 1 net collected subscription revenue from accounts you close.\n"
            "• **Payout Cadence:** Paid monthly within **15 days** of month-end.\n"
            "• **Equity Upside:** Milestone-based equity vesting tied to active paid brokerage & Business API retention targets (zero fixed payroll overhead)."
        ),
    },
    {
        "id": "gtm_launch",
        "title": "Go-To-Market Plan, Beta & Launch Milestones",
        "color": "blue",
        "attachment_filename": "Quotelytics_Go_To_Market_Plan.docx",
        "phrases": {
            "go to market": 8,
            "go-to-market": 8,
            "gtm": 8,
            "launch date": 7,
            "public launch": 7,
            "paid beta": 6,
            "soft launch": 6,
        },
        "keywords": {"december", "january", "roadmap", "milestone", "beta", "launch", "target"},
        "description": (
            "**Quotelytics Launch Timeline & Market Scope:**\n"
            "• **Paid Beta / Soft Launch:** **December 1, 2026**\n"
            "• **Target Public Launch:** **January 12, 2027**\n"
            "• **Target Market:** **1,500+ licensed Canadian freight brokerages & 3PLs** across the Ontario, Quebec, and Calgary freight corridor (`$40B+` Canadian commercial road freight market).\n"
            "• **Year 1 Goals:** 5 paid brokerages (Months 1–3) → 15 (Month 6) → 30 full-time founder milestone (Month 9) → 50 paid brokerages (Month 12)."
        ),
    },
    {
        "id": "rating_engine",
        "title": "Deterministic Rating Engine, Deficit Math & Canadian Benchmarks",
        "color": "blurple",
        "attachment_filename": None,
        "phrases": {
            "deficit rating": 8,
            "weight break": 7,
            "skid": 6,
            "backstop": 6,
            "benchmark": 6,
            "carriers": 5,
            "how does it work": 5,
            "rating engine": 7,
        },
        "keywords": {"cwt", "pallet", "ltl", "proposal", "pdf", "day & ross", "manitoulin"},
        "description": (
            "**How Quotelytics Quotes Work Under the Hood:**\n"
            "• **Deterministic Deficit Rating (`0.02ms`):** Evaluates actual weight vs. the next discount bracket automatically (e.g., saving shippers on an 850 lb shipment by deficit-rating at the 1,000 lb break).\n"
            "• **Skid / Pallet LTL Backstop:** Applies a **5,000 lb** capacity limit (+`100 lb` legal margin buffer) for safe skid-based LTL quoting.\n"
            "• **8 Built-In Canadian Benchmarks:** Day & Ross, Manitoulin, Midland, Maritime-Ontario, TForce, Vitran, Kindersley, and Armour — plus custom carrier `.xlsx`/`.csv` upload and instant branded PDF proposals."
        ),
    },
]


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


def _extract_docx_text(path: Path) -> str:
    try:
        import docx  # type: ignore
    except ImportError:
        return ""
    try:
        document = docx.Document(str(path))
    except Exception:
        return ""
    parts: List[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    for table in document.tables:
        for row in table.rows:
            row_text = " | ".join(
                cell.text.strip() for cell in row.cells if cell.text.strip()
            )
            if row_text:
                parts.append(row_text)
    return "\n".join(parts)


class ProjectKnowledgeIndex:
    """In-memory search index over workspace outreach docs, playbooks, and compliance files."""

    def __init__(self, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = Path(repo_root)
        self.outreach_dir = self.repo_root / "outreach"
        self.chunks: List[Dict[str, Any]] = []
        self.outreach_files: List[Path] = []
        self.build()

    def build(self) -> None:
        self.chunks = []
        self.outreach_files = []

        if self.outreach_dir.is_dir():
            for file_path in sorted(self.outreach_dir.iterdir()):
                if not file_path.is_file():
                    continue
                self.outreach_files.append(file_path)
                if file_path.suffix.lower() == ".docx":
                    text = _extract_docx_text(file_path)
                    self._add_document(file_path.name, text)
                elif file_path.suffix.lower() == ".csv":
                    try:
                        preview = "\n".join(
                            file_path.read_text(encoding="utf-8", errors="replace").splitlines()[:15]
                        )
                        self._add_document(file_path.name, preview)
                    except OSError:
                        pass

        markdown_roots = [
            self.repo_root / "marketing",
            self.repo_root / "incorporation_documents",
            self.repo_root / "compliance",
        ]
        for folder in markdown_roots:
            if not folder.is_dir():
                continue
            for md_file in sorted(folder.glob("*.md")):
                try:
                    self._add_document(
                        f"{folder.name}/{md_file.name}",
                        md_file.read_text(encoding="utf-8", errors="replace"),
                    )
                except OSError:
                    pass

        for single_doc in (
            self.repo_root / "README.md",
            self.repo_root / "README_FAILSAFE.md",
            BRAIN_PLAYBOOK_PATH,
        ):
            if single_doc.is_file():
                try:
                    self._add_document(
                        single_doc.name,
                        single_doc.read_text(encoding="utf-8", errors="replace"),
                    )
                except OSError:
                    pass

    def _add_document(self, source: str, text: str) -> None:
        if not text:
            return
        paragraphs = [p.strip() for p in re.split(r"\n{1,2}", text) if p.strip()]
        buffer: List[str] = []
        char_count = 0
        for para in paragraphs:
            buffer.append(para)
            char_count += len(para)
            if char_count >= 550:
                chunk_text = "\n".join(buffer)
                self.chunks.append(
                    {
                        "source": source,
                        "text": chunk_text,
                        "tokens": set(_tokenize(f"{source} {chunk_text}")),
                    }
                )
                buffer = []
                char_count = 0
        if buffer:
            chunk_text = "\n".join(buffer)
            self.chunks.append(
                {
                    "source": source,
                    "text": chunk_text,
                    "tokens": set(_tokenize(f"{source} {chunk_text}")),
                }
            )

    def match_outreach_file(self, query: str) -> Optional[Path]:
        if not self.outreach_files:
            return None
        q_lower = query.lower()
        q_tokens = set(_tokenize(query)) - {
            "send", "attach", "upload", "share", "download", "doc", "docx",
            "word", "file", "document", "copy", "spreadsheet", "xlsx", "csv",
        }
        if not q_tokens:
            return None

        best_path: Optional[Path] = None
        best_score = 0.0

        for path in self.outreach_files:
            stem_clean = re.sub(r"^\d+_", "", path.stem).replace("_", " ").lower()
            stem_tokens = set(_tokenize(stem_clean))
            overlap = q_tokens & stem_tokens
            if not overlap:
                continue
            score = len(overlap) * 2.0 + (len(overlap) / max(1, len(stem_tokens))) * 3.0
            if stem_clean in q_lower:
                score += 10.0
            if path.suffix.lower() == ".docx":
                score += 0.25
            if score > best_score and len(overlap) >= 2:
                best_score = score
                best_path = path

        # Prefer canonical numbered Sales Rep guide when ambiguous between 08 and 11
        if best_path and best_path.name == "08_Sales_Rep_Business_API_Setup_and_Troubleshooting_Guide.docx":
            alt = self.outreach_dir / "11_Sales_Rep_Business_API_Setup_and_Troubleshooting_Guide.docx"
            if alt.is_file():
                return alt
        return best_path

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return []

        q_clean = re.sub(r"\s+", " ", query.lower()).strip()
        scored: List[Tuple[float, Dict[str, Any]]] = []
        seen_sources: Set[str] = set()

        for chunk in self.chunks:
            overlap = len(q_tokens & chunk["tokens"])
            if overlap == 0:
                continue
            score = float(overlap)
            text_lower = chunk["text"].lower()
            if len(q_clean) >= 6 and q_clean in text_lower:
                score += 5.0
            if any(tok in chunk["source"].lower() for tok in q_tokens):
                score += 1.5
            scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: List[Dict[str, Any]] = []
        for score, chunk in scored:
            if chunk["source"] in seen_sources and len(results) < top_k:
                continue
            seen_sources.add(chunk["source"])
            results.append({"score": score, "source": chunk["source"], "text": chunk["text"]})
            if len(results) >= top_k:
                break
        return results


def _match_curated_topic(clean_query: str) -> Optional[Dict[str, Any]]:
    q_lower = clean_query.lower()
    q_tokens = set(_tokenize(q_lower))
    best_topic: Optional[Dict[str, Any]] = None
    best_score = 0

    for topic in CURATED_TOPICS:
        score = 0
        for phrase, weight in topic["phrases"].items():
            if phrase in q_lower:
                score += weight
        for kw in topic["keywords"]:
            if kw in q_tokens:
                score += 2
        if score > best_score:
            best_score = score
            best_topic = topic

    return best_topic if best_score >= 4 else None


def answer_sales_rep_question(
    question: str, knowledge_index: Optional[ProjectKnowledgeIndex] = None
) -> Dict[str, Any]:
    """Generate a read-only Discord support reply (embed + optional outreach attachment)."""
    cleaned = re.sub(r"<@!?\d+>", "", question or "").strip()
    if is_code_modification_request(cleaned):
        return {
            "embed_title": "Read-Only Sales Support Mode",
            "embed_description": (
                "I am configured in **Read-Only Sales Support Mode** so sales reps can "
                "safely ask any question about Quotelytics without modifying project code or "
                "database records. For code or platform changes, please ask Dylan to run the "
                "change in the Antigravity IDE."
            ),
            "embed_color": "amber",
            "footer": "Quotelytics Sales Rep Support (Read-Only)",
            "attachment_path": None,
        }

    index = knowledge_index or ProjectKnowledgeIndex()
    q_tokens = _tokenize(cleaned)

    if not cleaned or (len(q_tokens) == 0 and len(cleaned) < 25) or cleaned.lower() in {"hi", "hello", "help", "ping"}:
        return {
            "embed_title": "Quotelytics Sales Rep Support — How I Can Help",
            "embed_description": (
                "Ask me any question about the project right here in `#sales` (or mention `@Antigravity` anywhere)!\n\n"
                "**Popular Topics:**\n"
                "• **Pricing & Business API Formula** (*\"How is the Business API priced?\"*)\n"
                "• **Zero-Tech API Setup** (*\"How do I activate Business API for a customer?\"*)\n"
                "• **Error Troubleshooting** (*\"Customer got a 403 or 422 API error\"*)\n"
                "• **Competitor Intel** (*\"How do we compare to Tabi Connect?\"*)\n"
                "• **3PLs & Qualification** (*\"What is a 3PL and which tier fits them?\"*)\n"
                "• **Commissions, GTM & Docs** (*\"Send me the Beta Participation Agreement\"*)"
            ),
            "embed_color": "blurple",
            "footer": "Quotelytics Sales Rep Support (Read-Only)",
            "attachment_path": None,
        }

    attachment_path: Optional[Path] = None
    if _ATTACHMENT_INTENT_RE.search(cleaned):
        attachment_path = index.match_outreach_file(cleaned)

    curated = _match_curated_topic(cleaned)
    if curated:
        if attachment_path is None and _ATTACHMENT_INTENT_RE.search(cleaned) and curated.get("attachment_filename"):
            candidate = index.outreach_dir / str(curated["attachment_filename"])
            if candidate.is_file():
                attachment_path = candidate

        desc = curated["description"]
        if attachment_path is not None:
            desc += f"\n\n📎 **Attached:** `{attachment_path.name}`"

        return {
            "embed_title": curated["title"],
            "embed_description": desc[:4096],
            "embed_color": curated["color"],
            "footer": "Quotelytics Sales Support Playbook (Read-Only)",
            "attachment_path": str(attachment_path) if attachment_path else None,
        }

    if attachment_path is not None:
        preview_hits = index.search(attachment_path.stem.replace("_", " "), top_k=1)
        preview = preview_hits[0]["text"][:700] if preview_hits else "Requested document attached below."
        return {
            "embed_title": f"Requested Document: {attachment_path.name}",
            "embed_description": f"Attached `{attachment_path.name}` from the Quotelytics outreach package.\n\n**Preview:**\n{preview}",
            "embed_color": "blue",
            "footer": "Quotelytics Outreach Vault (Read-Only)",
            "attachment_path": str(attachment_path),
        }

    hits = index.search(cleaned, top_k=3)
    if hits:
        sections: List[str] = []
        for hit in hits:
            excerpt = hit["text"].strip()
            if len(excerpt) > 550:
                excerpt = excerpt[:547].rstrip() + "..."
            sections.append(f"**Source: `{hit['source']}`**\n{excerpt}")
        combined = "\n\n".join(sections)
        return {
            "embed_title": "Project Knowledge Answer",
            "embed_description": combined[:4096],
            "embed_color": "blue",
            "footer": "Quotelytics Project Corpus Search (Read-Only)",
            "attachment_path": None,
        }

    return {
        "embed_title": "Need More Detail on Your Question",
        "embed_description": (
            "I couldn't find an exact match for that phrase in the Quotelytics playbooks or documents. "
            "Try asking about **pricing**, **Business API setup**, **401/402/403/422 errors**, "
            "**Tabi Connect**, **3PLs**, **commissions**, **CBCA incorporation**, or **Go-To-Market dates**."
        ),
        "embed_color": "blurple",
        "footer": "Quotelytics Sales Rep Support (Read-Only)",
        "attachment_path": None,
    }


def is_message_targeted_at_bot(
    msg: Dict[str, Any], channel_id: str, bot_user_id: str = BOT_USER_ID
) -> bool:
    """Return True if the bot should answer this Discord message."""
    author = msg.get("author") or {}
    if author.get("bot"):
        return False

    content = (msg.get("content") or "").strip()
    if not content:
        return False

    if str(channel_id) == SALES_CHANNEL_ID:
        return True

    if f"<@{bot_user_id}>" in content or f"<@!{bot_user_id}>" in content:
        return True
    if "antigravity" in content.lower():
        return True
    return any(str(m.get("id")) == bot_user_id for m in (msg.get("mentions") or []))


def send_bot_reply(
    channel_id: str,
    reply_to_message_id: str,
    answer: Dict[str, Any],
    http_transport: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Post an inline Bot API reply (with optional multipart file attachment)."""
    payload: Dict[str, Any] = {
        "message_reference": {"message_id": str(reply_to_message_id)},
        "embeds": [
            {
                "title": str(answer["embed_title"])[:256],
                "description": str(answer["embed_description"])[:4096],
                "color": parse_color(answer.get("embed_color") or "blurple"),
                "footer": {"text": str(answer.get("footer") or "Quotelytics Sales Support")[:2048]},
            }
        ],
    }

    attachment_path = answer.get("attachment_path")
    if attachment_path and Path(attachment_path).is_file():
        token = _resolve_bot_token()
        body_bytes, content_type = _build_multipart_body(payload, str(attachment_path))
        url = f"{DISCORD_API_BASE}/channels/{urllib.parse.quote(str(channel_id))}/messages"
        headers = {
            "Authorization": f"Bot {token}",
            "User-Agent": USER_AGENT,
            "Content-Type": content_type,
        }
        transport = http_transport or _default_http_transport
        status_code, parsed = _normalize_transport_result(
            transport(method="POST", url=url, headers=headers, body=body_bytes)
        )
        if status_code >= 400:
            raise RuntimeError(f"Discord API error {status_code}: {parsed}")
        return parsed

    return discord_api_request(
        "POST",
        f"/channels/{urllib.parse.quote(str(channel_id))}/messages",
        body=payload,
        http_transport=http_transport,
    )


def load_bot_state(state_path: Path = DEFAULT_STATE_PATH) -> Dict[str, Any]:
    if not state_path.is_file():
        return {"channels": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("channels"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"channels": {}}


def save_bot_state(state: Dict[str, Any], state_path: Path = DEFAULT_STATE_PATH) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def init_bot_state(
    state_path: Path = DEFAULT_STATE_PATH,
    channels: List[Tuple[str, str, bool]] = WATCHED_CHANNELS,
    http_transport: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Seed state with the current latest message ID in each watched channel."""
    state = load_bot_state(state_path)
    channel_map = state.setdefault("channels", {})
    for _name, cid, _mention_only in channels:
        if channel_map.get(cid):
            continue
        raw = discord_api_request(
            "GET",
            f"/channels/{cid}/messages?limit=1",
            http_transport=http_transport,
        )
        if isinstance(raw, list) and raw:
            channel_map[cid] = str(raw[0]["id"])
        else:
            channel_map[cid] = "0"
    save_bot_state(state, state_path)
    return state


def poll_channels_once(
    knowledge_index: ProjectKnowledgeIndex,
    state_path: Path = DEFAULT_STATE_PATH,
    channels: List[Tuple[str, str, bool]] = WATCHED_CHANNELS,
    http_transport: Optional[Callable[..., Any]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> int:
    """Poll watched channels once for new messages and reply inline."""
    state = load_bot_state(state_path)
    channel_map = state.setdefault("channels", {})
    replies_sent = 0
    state_changed = False

    for ch_name, cid, _mention_only in channels:
        last_id = channel_map.get(cid)
        if not last_id:
            raw = discord_api_request(
                "GET",
                f"/channels/{cid}/messages?limit=1",
                http_transport=http_transport,
            )
            channel_map[cid] = str(raw[0]["id"]) if raw else "0"
            state_changed = True
            continue

        query_path = f"/channels/{cid}/messages?limit=25"
        if last_id != "0":
            query_path += f"&after={urllib.parse.quote(str(last_id))}"

        raw_messages = discord_api_request(
            "GET", query_path, http_transport=http_transport
        )
        if not isinstance(raw_messages, list) or not raw_messages:
            continue

        chronological = sorted(raw_messages, key=lambda m: int(m["id"]))
        for msg in chronological:
            msg_id = str(msg["id"])
            if int(msg_id) <= int(last_id):
                continue

            if is_message_targeted_at_bot(msg, cid):
                answer = answer_sales_rep_question(
                    msg.get("content") or "", knowledge_index=knowledge_index
                )
                send_bot_reply(
                    cid, msg_id, answer, http_transport=http_transport
                )
                replies_sent += 1
                if log_fn:
                    author = (msg.get("author") or {}).get("username", "unknown")
                    log_fn(
                        f"Replied in #{ch_name} to @{author} ({msg_id}) -> {answer['embed_title']}"
                    )

            channel_map[cid] = msg_id
            last_id = msg_id
            state_changed = True
            save_bot_state(state, state_path)

    if state_changed:
        save_bot_state(state, state_path)
    return replies_sent


def run_polling_daemon(
    poll_interval: float = 4.0, state_path: Path = DEFAULT_STATE_PATH
) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    def _log(text: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {text}", flush=True)

    _log("Indexing Quotelytics sales & project documentation...")
    index = ProjectKnowledgeIndex()
    _log(
        f"Indexed {len(index.chunks)} knowledge chunks and {len(index.outreach_files)} outreach files."
    )

    state = init_bot_state(state_path=state_path)
    _log(f"Initialized channel checkpoints: {state['channels']}")
    _log("Discord Sales Rep Support Bot is online (Read-Only Mode). Watching #sales & mentions.")

    while True:
        try:
            poll_channels_once(
                knowledge_index=index, state_path=state_path, log_fn=_log
            )
            time.sleep(poll_interval)
        except KeyboardInterrupt:
            _log("Shutting down Discord Sales Rep Support Bot.")
            break
        except Exception as exc:
            msg = str(exc)
            backoff = poll_interval * 2
            if "429" in msg and "retry_after" in msg:
                match = re.search(r'"retry_after"\s*:\s*([0-9.]+)', msg)
                if match:
                    backoff = max(2.0, float(match.group(1)) + 0.5)
            _log(f"Poll warning ({exc}); retrying in {backoff:.1f}s")
            time.sleep(backoff)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the 24/7 Read-Only Discord Sales Rep Support Bot."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=4.0,
        help="Polling interval in seconds (default: 4.0).",
    )
    parser.add_argument(
        "--init-state",
        action="store_true",
        help="Seed last_message_id state and exit without polling.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll channels once and exit.",
    )
    args = parser.parse_args(argv)

    if args.init_state:
        state = init_bot_state()
        print(json.dumps(state, indent=2))
        return 0

    if args.once:
        index = ProjectKnowledgeIndex()
        count = poll_channels_once(knowledge_index=index)
        print(json.dumps({"ok": True, "replies_sent": count}, indent=2))
        return 0

    run_polling_daemon(poll_interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
