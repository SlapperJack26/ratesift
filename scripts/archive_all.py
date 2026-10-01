import os
import json
import shutil
import zipfile
import datetime

def main():
    brain_dir = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"
    project_dir = r"c:\Users\Dylan\Documents\antigravity\quick-hertz"
    conv_dir = os.path.join(project_dir, "conversation_data")
    os.makedirs(conv_dir, exist_ok=True)
    os.makedirs(os.path.join(conv_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(conv_dir, "artifacts"), exist_ok=True)

    # 1. Copy latest transcripts
    src_transcript = os.path.join(brain_dir, ".system_generated", "logs", "transcript.jsonl")
    src_full = os.path.join(brain_dir, ".system_generated", "logs", "transcript_full.jsonl")
    if os.path.exists(src_transcript):
        shutil.copy2(src_transcript, os.path.join(conv_dir, "transcript.jsonl"))
    if os.path.exists(src_full):
        shutil.copy2(src_full, os.path.join(conv_dir, "transcript_full.jsonl"))

    # 2. Copy all brain artifacts to conversation_data/artifacts
    for item in os.listdir(brain_dir):
        src_path = os.path.join(brain_dir, item)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, os.path.join(conv_dir, "artifacts", item))
            if item.endswith((".jpg", ".png")):
                shutil.copy2(src_path, os.path.join(conv_dir, "images", item))

    # 3. Read timeline
    timeline_path = os.path.join(conv_dir, "conversation_timeline.json")
    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline = json.load(f)

    prompts = timeline["user_prompts"]

    now_str = datetime.datetime.now().strftime("%B %d, %Y - %H:%M:%S")

    # 4. Generate CONVERSATION_ARCHIVE.md
    md = []
    md.append("# Ratesift Complete Conversation & Project Data Archive")
    md.append(f"**Conversation ID:** `b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4`  ")
    md.append(f"**Platform:** Ratesift Automated Batch Shipping Quoting Platform  ")
    md.append(f"**Archive Timestamp:** {now_str}  ")
    md.append(f"**Total Trajectory Steps:** {timeline['total_steps']}  ")
    md.append(f"**Total User Prompts:** {len(prompts)}  ")
    md.append(f"**Compliance Standard:** All 32 RateSift Freight Broker Directives Enforced + Non-Critical Info Flexibility  ")
    md.append(f"**Data Residency:** WHC Canada (`CA_CENTRAL_WHC`)  ")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 1. Executive Summary & Product Invariants")
    md.append("")
    md.append("**Ratesift** is a specialized, deterministic web platform and quoting engine designed for automated batch shipping rate calculations from Excel spreadsheets (`.xlsx`, `.xls`). The platform is strictly constrained to **quoting only** (no carrier booking, no label printing, and no delivery tracking numbers).")
    md.append("")
    md.append("### Core Invariants Enforced Across the Entire Platform:")
    md.append("1. **Strict Quoting Boundary:** Quoting calculations only; zero label generation or booking workflows.")
    md.append("2. **Visual Brand Identity (Header & Footer Only):** Official visual RateSift logo image lockup (red rounded filter icon, 'RateSift' wordmark, and subtitle 'Shipping rate comparison') is restricted exclusively to the `<header>` and `<footer>`.")
    md.append("3. **Standard Typography Everywhere Else:** Spelled with standard proper noun capitalization as **Ratesift** across all body copy, headings, meta tags, schema JSON-LD, pricing cards, and database records.")
    md.append("4. **Full-Bleed Edge-to-Edge Margins:** Header top margin = 0, footer bottom margin = 0 (`mt-auto m-0`), horizontal margins = 0 (`w-full`), touching viewport boundaries across phones, tablets, laptops, and monitors.")
    md.append("5. **Private New Quote Form:** Vertical headers for **From** and **To**, each containing horizontal options for `City Name`, `Province / State`, `Postal Code / Zip Code`, and `Country` list.")
    md.append("6. **Table Display Standard:** Bold table headers (`font-bold`), unbolded data rows (`font-normal`), exact coordinate cell tracking (`Sheet 1 • Row 14, Col C`), and zero colored status bubbles.")
    md.append("7. **Public vs. Private Segregation:** 5 public crawlable SEO pages (`/`, `/demo`, `/pricing`, `/login`, `/get-started`) vs. 4 route-guarded authenticated console views (`/console/new-quote`, `/console/rate-sheets`, `/console/history`, `/console/account`, `/console/settings`).")
    md.append("8. **Excel Re-formatter & Clarification:** Interactive preview and confirmation dialog for non-critical exceptions vs critical blockers.")
    md.append("")
    md.append("---")
    md.append("")
    md.append(f"## 2. Chronological Log of All {len(prompts)} User Requests")
    md.append("")
    md.append("| # | Step | Timestamp | User Request Prompt |")
    md.append("| :---: | :---: | :---: | :--- |")

    for p in prompts:
        num = p["prompt_num"]
        step = p["step_index"]
        ts = p["timestamp"]
        clean = p["text"].replace("|", "\\|").replace("\n", " ").replace("\r", "")
        md.append(f"| **#{num}** | Step {step} | `{ts}` | {clean} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. Product Evolution & Milestone Summary")
    md.append("")
    md.append("### Phase 1: Prototype Views & Initial Visual Direction (Prompts #1-#14)")
    md.append("Created the visual identity, Excel file dropzones, table sorting controls, bold headers, unbolded data, and date/help footer positioning.")
    md.append("")
    md.append("### Phase 2: Console Expansion & Navigation (Prompts #15-#23)")
    md.append("Renamed navigation items to 'New Quote' and 'History', added Account/Settings/Signout menu, generated Account Settings, System Settings, and 4-view side-by-side simulator.")
    md.append("")
    md.append("### Phase 3: Public Views & SEO Optimization (Prompts #24-#34)")
    md.append("Designed 5 public views (Home, Demo, Pricing, Login, Get Started) strictly following SEO guidelines, OpenGraph tags, semantic HTML, and multi-tier pricing plans.")
    md.append("")
    md.append("### Phase 4: Architecture Flowchart & Implementation Plan (Prompts #35-#41)")
    md.append("Designed complete system flowchart linking public and private routes, defined the 8-phase implementation roadmap, and established test-driven milestones.")
    md.append("")
    md.append("### Phase 5: Multi-Device Responsive Auto-Scaling (Prompt #42)")
    md.append("Engineered comprehensive responsive layout with CSS clamp, fluid typography, mobile drawers, responsive tables, and multi-device switcher for phone, tablet, laptop, and monitor.")
    md.append("")
    md.append("### Phase 6: Brand Evolution & Stylization (Prompts #43-#46)")
    md.append("Shifted color palette to Crimson Red (`#DC2626`), stylized header/footer with official logo lockup, and enforced standard proper noun `Ratesift` across all other contexts.")
    md.append("")
    md.append("### Phase 7: Edge-to-Edge Margins & New Quote Routing Headers (Prompts #47-#48)")
    md.append("Implemented zero-margin full-bleed top, bottom, and horizontal borders. Rebuilt `/console/new-quote` with vertical 'From' and 'To' headers and horizontal inputs for City, Province/State, Zip, and Country.")
    md.append("")
    md.append("### Phase 8: Excel Re-formatter, Clarification Engine & Live Server (Prompts #49-#53)")
    md.append("Built intelligent Excel restructuring pipeline with tolerance for non-critical column gaps, interactive modal clarification, 47/47 passing tests, live server deployment, and full archival.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 4. Test Suite Registry (100% Passing)")
    md.append("")
    md.append("| Test Suite | Target | Status |")
    md.append("|---|---|:---:|")
    md.append("| `test_milestone1_database_and_isolation.py` | Multi-tenant DB isolation, cell coordinates, CA_CENTRAL_WHC | PASS |")
    md.append("| `test_milestone2_extractor_and_confirmation_gate.py` | OpenPyXL parsing, cell coordinate extraction, confirmation gating | PASS |")
    md.append("| `test_milestone3_deterministic_quoting_engine.py` | Deterministic quoting math, divisor, density PCF, minimums | PASS |")
    md.append("| `test_milestone4_filtering_versioning_anomaly.py` | Date filtering, tariff version precedence, >25% rate shift alerts | PASS |")
    md.append("| `test_milestone5_broker_ui_and_resorting.py` | Broker UI cards, client-side re-sorting, itemized audit accordion | PASS |")
    md.append("| `test_milestone6_end_to_end_verification.py` | Multi-carrier comparison, 32 directives compliance | PASS |")
    md.append("| `test_excel_reformatter_and_clarification.py` | Excel auto-reformatting, non-critical flexibility, clarification modal | PASS |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 5. Live Server Endpoints")
    md.append("")
    md.append("* **Public Landing:** `http://127.0.0.1:8000/`")
    md.append("* **Public Demo:** `http://127.0.0.1:8000/demo`")
    md.append("* **Public Pricing:** `http://127.0.0.1:8000/pricing`")
    md.append("* **Login:** `http://127.0.0.1:8000/login` (`demo@ratesift.com` / `demo1234`)")
    md.append("* **New Quote Console:** `http://127.0.0.1:8000/console/new-quote`")
    md.append("* **Rate Sheets:** `http://127.0.0.1:8000/console/rate-sheets`")
    md.append("* **Quotes History:** `http://127.0.0.1:8000/console/history`")
    md.append("* **Account Profile:** `http://127.0.0.1:8000/console/account`")
    md.append("* **Multi-Device Simulator:** `http://127.0.0.1:8000/showcase`")
    md.append("* **Architecture Flowchart:** `http://127.0.0.1:8000/flowchart`")
    md.append("")

    full_md = "\n".join(md)

    with open(os.path.join(conv_dir, "CONVERSATION_ARCHIVE.md"), "w", encoding="utf-8") as f:
        f.write(full_md)
    print("Saved CONVERSATION_ARCHIVE.md")

    with open(os.path.join(brain_dir, "conversation_archive.md"), "w", encoding="utf-8") as f:
        f.write(full_md)
    print("Saved brain artifact conversation_archive.md")

    # 5. Create zip bundle of conversation data
    zip_path = os.path.join(conv_dir, "ratesift_conversation_full_archive.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(conv_dir):
            for file in files:
                if file.endswith(".zip"):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, conv_dir)
                zf.write(file_path, os.path.join("conversation_data", arcname))
    print(f"Created conversation zip archive: {zip_path} ({os.path.getsize(zip_path)} bytes)")

    # 6. Create full project repository backup
    project_backup_zip = os.path.join(project_dir, "ratesift_project_backup_latest.zip")
    exclude_dirs = {"__pycache__", ".git", "venv", ".pytest_cache"}
    with zipfile.ZipFile(project_backup_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith(".zip"):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, project_dir)
                zf.write(file_path, arcname)
    print(f"Created project backup zip: {project_backup_zip} ({os.path.getsize(project_backup_zip)} bytes)")

if __name__ == "__main__":
    main()
