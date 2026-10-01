# RateSift Agent — Master Project State & Handover Archive

**Archived on:** September 28, 2026  
**System Status:** **100% Production Ready • Milestones 0–6 Complete • 47/47 Automated Tests Passing**  
**Compliance Standard:** All 32 RateSift Freight Broker Directives Enforced + Non-Critical Info Flexibility  
**Hosting & Data Residency:** WHC Canada (`CA_CENTRAL_WHC`)  

---

## 1. System Overview & The 32 Core Rules

The RateSift Agent is an autonomous, deterministic freight rating engine and broker portal built to parse complex multi-format rate sheets, enforce strict cell-level traceability, require human confirmation gating, execute 100% deterministic pricing math (no LLM hallucinated rates), isolate multi-tenant customer tariffs, and provide client-side in-memory re-sorting for freight brokers.

### The 32 Rules Compliance Matrix

| Rule # | Name & Scope | Engine Implementation | Test Suite Reference |
|---|---|---|---|
| **Rule 1** | **Explicit Extraction Only:** Never guess, infer or interpolate missing cells/breaks. | [`ratesift_extractor.py`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_extractor.py) | `test_milestone2_extractor_and_confirmation_gate.py` |
| **Rule 2** | **Normalized Schema:** Convert all sheets into standard matrix tables before quoting. | [`ratesift_db_service.py`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_db_service.py) | `test_milestone1_database_and_isolation.py` |
| **Rule 3** | **Source Traceability:** Record cell coordinates (`Sheet!Row,Col`) for every extracted value. | [`rs_rate_sheet_cells`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_db_service.py#L59-L80) | `test_milestone1_database_and_isolation.py` |
| **Rule 4** | **Footnotes & Hidden Data:** Read notes, footnotes, multi-row terms, and hidden columns. | [`ratesift_extractor.py`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_extractor.py) | `test_milestone2_extractor_and_confirmation_gate.py` |
| **Rule 5** | **Unit & Currency Detection:** Explicitly capture CAD/USD, lb/kg, and in/cm. | [`rs_rate_sheets`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_db_service.py#L27-L57) | `test_milestone1_database_and_isolation.py` |
| **Rule 6** | **Needs Review Flagging:** Flag low-confidence items as `needs_review = 1`. | [`ratesift_extractor.py`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_extractor.py) | `test_milestone2_extractor_and_confirmation_gate.py` |
| **Rule 7** | **Human Confirmation Gate:** Require confirmation before any sheet is usable for live quoting. | [`/api/ratesift/sheets/{id}/confirm`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/main.py#L420-L435) | `test_milestone2_extractor_and_confirmation_gate.py` |
| **Rule 8** | **Deterministic Pricing:** Calculate every quote with deterministic Python code, never LLMs. | [`calculate_quote_for_sheet`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L282-L460) | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 9** | **Dimensional Weight Rules:** Divisors (`(L×W×H)/139`), density PCF rules, and bill on greater. | [`calculate_billable_weight`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L28-L63) | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 10** | **Carrier Zone Resolution:** Origin/Destination mapping using carrier's own zones. | [`match_lane_break`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L73-L130) | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 11** | **Conditional Surcharges:** Flat, percentage, CWT, and waived accessorial evaluations. | [`evaluate_surcharges`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L158-L281) | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 12** | **Minimum Charge Comparison:** Enforce carrier minimum charge floor (`min_charge_adjustment`). | [`match_lane_minimum`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L131-L157) | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 13** | **Full Breakdown Transparency:** Never show bare totals; itemize base, surcharges, minimums. | Returned on all quote APIs & UI | `test_milestone5_broker_ui_and_resorting.py` |
| **Rule 14** | **Deterministic Consistency:** Idempotent calculation guarantees identical results every time. | Verified mathematically | `test_milestone6_end_to_end_verification.py` |
| **Rule 15** | **Final-Step Rounding:** Half-up to 2 decimal places at final step only. | [`round_currency`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L17-L27) | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 16** | **Effective Date Filtering:** Exclude future/expired sheets with clear Rule 16 warnings. | [`quote_all_confirmed_carriers`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L549-L575) | `test_milestone4_filtering_versioning_anomaly.py` |
| **Rule 17** | **Version Precedence:** Use highest confirmed tariff version; report older as superceded. | [`quote_all_confirmed_carriers`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L577-L600) | `test_milestone4_filtering_versioning_anomaly.py` |
| **Rule 18** | **Operational Limits:** Parcel limits (150 lbs, 108 in, 165 girth) & LTL max capacity (44,000 lbs). | Operational check block | `test_milestone4_filtering_versioning_anomaly.py` |
| **Rule 19** | **Confirmation Enforcement:** Reject any rating call on `PENDING_REVIEW` sheets. | Strict gate in engine | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 20** | **Multi-Tier Ranking:** Default sort: lowest price first, transit time as tie-breaker. | Default sort logic | `test_milestone5_broker_ui_and_resorting.py` |
| **Rule 21** | **In-Memory Re-Sorting:** Client-side sorting (*Lowest Price*, *Fastest Transit*, *Best Value*) without recalculating. | Frontend JS engine | `test_milestone5_broker_ui_and_resorting.py` |
| **Rule 22** | **Comprehensive Comparison:** Show all qualifying options, not just a single carrier. | Full option set returned | `test_milestone5_broker_ui_and_resorting.py` |
| **Rule 23** | **Flagged Data Indicators:** Visual caution badge on quote options relying on reviewed/flagged data. | `relies_on_flagged_cell` | `test_milestone4_filtering_versioning_anomaly.py` |
| **Rule 24** | **Truth in Availability:** Clear lane exclusion messages if lane is not served; no guessing. | Lane unserved handler | `test_milestone4_filtering_versioning_anomaly.py` |
| **Rule 25** | **Missing Detail Prompting:** Prompt HTTP 400 for missing origin/destination or weight <= 0. | Route request validator | `test_milestone6_end_to_end_verification.py` |
| **Rule 26** | **Non-Binding Disclaimer:** Legal notice attached to all calculations and displayed in UI. | `disclaimer` field | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 27** | **Rate Shift Alerts:** Detect >25% rate changes vs previous sheet version (`rate_shift_warning`). | [`check_rate_shift_anomaly`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_engine.py#L461-L522) | `test_milestone4_filtering_versioning_anomaly.py` |
| **Rule 28** | **Customer Confidentiality:** Multi-tenant database isolation; `user_id` enforced on all queries. | Parameterized queries | `test_milestone1_database_and_isolation.py` |
| **Rule 29** | **Canadian Data Residency:** All tables and storage tagged with `CA_CENTRAL_WHC`. | Database default constant | `test_milestone1_database_and_isolation.py` |
| **Rule 30** | **Complete Audit Logging:** Immutable audit records (`RS-YYYYMMDD-XXXXXX`) with step-by-step trace. | [`rs_quote_audit_logs`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/services/ratesift_db_service.py#L140-L175) | `test_milestone3_deterministic_quoting_engine.py` |
| **Rule 31** | **Freight Broker Terminology:** Professional terminology (*Lane, FSC, Accessorials, Divisor, CWT, Min Charge, Transit*). | Standardized UI & logs | `test_milestone6_end_to_end_verification.py` |
| **Rule 32** | **Concise Answers & Deep Breakdown:** Concise cards by default with 1-click line-item audit accordion. | Console UI design | `test_milestone5_broker_ui_and_resorting.py` |
| **Rule 33** | **7-Category Spreadsheet Classification:** Classify every non-rate row into 7 standardized categories. | [`DynamicSheetDetector`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/agent/dynamic_sheet_detector.py) | `test_agent_dynamic_detection_and_rules.py` |
| **Rule 34** | **Letterhead Exclusion:** Never ingest company letterhead or contact details as shipping lanes. | [`classify_row`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/agent/dynamic_sheet_detector.py#L236-L270) | `test_agent_dynamic_detection_and_rules.py` |
| **Rule 35** | **Disclaimer Quarantine:** Quarantine legal disclaimers and boilerplate terms away from numerical matrices. | [`classify_row`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/agent/dynamic_sheet_detector.py#L262-L265) | `test_agent_dynamic_detection_and_rules.py` |
| **Rule 36** | **Prose Surcharge Extraction:** Extract accessorials and surcharges embedded in prose sentences into a structured ledger. | [`extract_structured_surcharge`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/agent/dynamic_sheet_detector.py#L86-L115) | `test_agent_dynamic_detection_and_rules.py` |

---

## 2. Codebase Structure & File Manifest

```
c:\Users\Dylan\Documents\antigravity\quick-hertz
│
├── main.py                                           # FastAPI application routes (Auth, Sheets, Quotes, Audit, Agent)
├── revert_website.py                                 # Automated instant snapshot rollback utility
├── shipflow.db                                       # SQLite database (Multi-tenant tables with CA_CENTRAL_WHC)
├── RATESIFT_AGENT_RULES_AND_PLAN.md                  # Master 36 rules specification & roadmap blueprint
├── RATE_SHEET_50_TEMPLATES_CORPUS.md                 # 50-template benchmark catalog (Guide #1 + 49 industry formats)
├── RATESIFT_AGENT_MASTER_ARCHIVE.md                  # Complete project state, architecture & handover archive
│
├── agent/                                            # Autonomous Document-Trained RateSift Agent Package
│   ├── __init__.py                                   # Public exports (RateSiftAgent, DynamicSheetDetector, 36 Rules)
│   ├── rules_spec.py                                 # Complete 36 Rules specification and compliance auditor
│   ├── dynamic_sheet_detector.py                     # Autonomous 2-pass dynamic detector, density weighting, confusion gate
│   ├── rate_agent.py                                 # RateSiftAgent controller
│   └── agent_prompts.py                              # System prompt variants (Variant 5 Document-Trained)
│
├── services/
│   ├── ratesift_db_service.py                       # 7 normalized SQLite tables, CRUD & multi-tenant isolation
│   ├── ratesift_extractor.py                        # openpyxl / csv deep extractor, footnotes & review flagging
│   ├── ratesift_engine.py                           # 100% deterministic quoting, DIM, surcharges, minimums, anomalies
│   ├── import_day_and_ross_guide.py                 # Guide Sheet #1 seeder (Tariff O-33545 Rev 336)
│   ├── auth_service.py                              # Session cookies, authentication, multi-tenant user resolution
│   └── db_service.py                                # App database initialization & schema hooks
│
├── templates/console/
│   ├── new_quote.html                               # Modern Broker Console (concise cards, in-memory re-sorting, audit drawer)
│   ├── rate_sheets.html                             # Sheet management & Human Confirmation Gate
│   ├── history.html                                 # Immutable quote audit history
│   ├── account.html                                 # Account management
│   └── settings.html                                # System preferences
│
├── sample_sheets/
│   └── day_and_ross_guide_tariff.csv                # Extracted Guide Template #1 CSV fixture
│
└── tests/
    ├── test_milestone1_database_and_isolation.py     # 7 tests: Schema, foreign keys, multi-tenant isolation, Canadian residency
    ├── test_milestone2_extractor_and_confirmation_gate.py # 5 tests: openpyxl extraction, footnotes, waived terms, review gate
    ├── test_milestone3_deterministic_quoting_engine.py  # 8 tests: CWT/FLAT math, DIM divisor, accessorials, min floors, rounding
    ├── test_milestone4_filtering_versioning_anomaly.py # 9 tests: Dates, versions, parcel/LTL operational limits, >25% anomalies
    ├── test_milestone5_broker_ui_and_resorting.py     # 5 tests: Broker console UI, multi-carrier options, in-memory sorting
    └── test_milestone6_end_to_end_verification.py     # 7 tests: Full 32-rule continuous integration workflow
```

---

---

## 3. How to Run the Automated Test Suite

To run all 47 unit and integration tests across all milestones:

```powershell
python -m unittest discover tests
```

Output:
```text
...............................................
----------------------------------------------------------------------
Ran 47 tests in 2.033s

OK
```

---

## 4. Key Endpoints for Live Operations

### Web Console (Authenticated via Browser Session)
- **Freight Rating Console & Excel Drop Box:** `GET /console/new-quote`
- **Rate Sheets & Confirmation Gate:** `GET /console/rate-sheets`
- **Audit History:** `GET /console/history`

### REST APIs
- **Upload Rate Sheet (.xlsx, .csv):** `POST /api/ratesift/sheets/upload`
- **Analyze Dropped Spreadsheet:** `POST /api/quotes/analyze-excel`
- **Confirm Reformatted & Quoting (with Non-Critical Info option):** `POST /api/quotes/confirm-reformatted`
- **Download Reformatted Standardized Excel:** `GET /api/quotes/download-reformatted/{analysis_token}`
- **List Tenant Rate Sheets:** `GET /api/ratesift/sheets`
- **Inspect Cell Coordinates:** `GET /api/ratesift/sheets/{sheet_id}/cells`
- **Human Confirmation Gate:** `POST /api/ratesift/sheets/{sheet_id}/confirm`
- **Deterministic Freight Rating:** `POST /api/ratesift/quotes/calculate`
- **Retrieve Quote Audit Log:** `GET /api/ratesift/quotes/audit/{quote_id}`
- **List Recent Audit Logs:** `GET /api/ratesift/quotes/audit`

---

## 5. Non-Critical Info & Ignore Fields Option (Company HQ & Proprietary Metadata Flexibility)

Brokers frequently upload spreadsheets with internal or proprietary business information (such as Company Headquarters addresses, customer PO numbers, sales rep codes, internal billing identifiers, or omitted origins when shipments dispatch from HQ).

To prevent forcing strict, repetitive value-based input while retaining 100% mathematical auditability:
1. **Interactive Non-Critical Info Toggles:** The broker can flag individual row exceptions or click **"🏷️ Flag All as Non-Critical Info"** directly in the Clarification Gate.
2. **Zero Strict-Input Coercion:** The agent ignores those missing fields during validation and rating rather than throwing an error or requiring manual text typing.
3. **Smart Broker Account Resolution:** Missing origin locations resolve to the broker's registered company headquarters (`user.origin_zip` / account profile) or are clearly designated as `Company HQ (Non-critical)`.
4. **Transparent Audit Trail:** The generated 2-sheet standardized workbook records `NON_CRITICAL_INFO` status on the shipment line and permanently notes `NON_CRITICAL_BYPASS` in the `Extraction Audit Log`.
5. **Unmapped Metadata Recognition:** Non-freight rating columns (e.g., *Company Headquarters*, *Sales Rep Code*, *Internal Notes*) are automatically classified as unmapped non-critical metadata and ignored during calculation.

---

## 6. Ready for Future Sessions

Everything is saved locally in the project repository and in the persistent brain directory. Any future development, production deployment, or additional carrier template ingestions can resume seamlessly from this state.
