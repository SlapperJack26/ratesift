# Rate-Sheet Header Failsafe + Excel Formatting Agent

> **Failsafe Contract:** A wrong quote is worse than a pause. When in doubt, the agent stops and asks the user to map the columns manually. It must never guess silently on required fields.

---

## 1. System Overview & Architecture

RateSift allows freight brokers to upload carrier rate sheets (`.xlsx`, `.csv`). The **Rate-Sheet Header Failsafe** intercepts every spreadsheet, performs deep structural inspections, detects pricing modes, computes confidence scores, and gates processing until column assignments are 100% verified.

```
Uploaded Sheet (.xlsx, .csv)
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ Ingestion & Safety Guard (app/ingest.py)               │
│ • Zip-bomb inspection (< 100MB, < 10k entries, < 100:1) │
│ • Capped scan load (500 rows × 100 cols)               │
│ • Merged cell forward-filling                          │
│ • Uncached formula rejection                           │
│ • NFKC, zero-width char & NBSP normalization           │
└───────────────────────────────────┬────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────┐
│ Detection & Failsafe Engine (app/detect.py)            │
│ • Origin & Destination scoring                         │
│ • Pricing Mode: Weight (breaks + unit) vs Skid/Pallet   │
│ • Conflict detection (competing columns)               │
│ • Confidence Thresholds:                               │
│     ≥ 0.85: Auto-map silently                          │
│     0.50 - 0.85: Auto-map but require confirmation     │
│     < 0.50: Require manual mapping                     │
└───────────────────┬────────────────────────┬───────────┘
                    │                        │
       High Conf (≥ 0.85)             Ambiguous / Conflict / Needs Conf
                    │                        │
                    ▼                        ▼
           status: "ready"          status: "needs_mapping"
                    │                        │
                    │               ┌────────┴──────────────────────────┐
                    │               │ Frontend Mapping Modal (Phase 4)   │
                    │               │ • Sticky 12-row preview table     │
                    │               │ • Conflict badges & highlights    │
                    │               │ • Mode & Unit selector            │
                    │               │ • POST /jobs/{id}/mapping         │
                    │               └────────┬──────────────────────────┘
                    │                        │ Confirmed
                    ▼                        ▼
┌────────────────────────────────────────────────────────┐
│ Atomic Compare-and-Set Gate (POST /jobs/{id}/process)  │
│ • Rejects any job with status != 'ready' (HTTP 409)    │
│ • Full load caps: 25k rows, 100 cols, 1M total cells   │
│ • Downstream overrides passed to reformatter           │
│ • Output formula neutralization (=, +, -, @, \t, \r)   │
│ • Byte-identical original file immutability            │
└────────────────────────────────────────────────────────┘
```

---

## 2. The 14 Invariants (The Failsafe Contract)

1. **Origin and Destination are always required.**
2. **Plus exactly one pricing mode:**
   - **Weight mode:** Weight-break columns (`-45`, `+100`, `+500`, etc.) **and** an explicit weight unit (`lb` or `kg`).
   - **Skid mode:** Skid/pallet rate columns (`1 PL`, `2 PL`) or a skid count column with rate column.
3. If the sheet exhibits both modes or neither mode, **ask the user which one to quote**. Never guess.
4. **Confidence thresholds:**
   - $\ge 0.85$: Auto-map silently.
   - $0.50 - 0.85$: Suggest mapping, but require user confirmation.
   - $< 0.50$: Require manual mapping.
5. **Content alone never auto-maps a required field:** Header signal is strictly required. (Protects against `Col A` city regression).
6. **Conflicts trigger the prompt:** When columns compete for a field or one column matches two fields, populate `conflicts` and halt for user resolution.
7. **The process step is gated:** `POST /jobs/{id}/process` returns `HTTP 409` unless status is `ready`.
8. **Weight unit required in weight mode:** A weight sheet without a detected unit cannot reach `ready` automatically.
9. **Cancelling leaves file untouched:** Calling `POST /jobs/{id}/cancel` expires the job without mutating the upload.
10. **LLM suggestions are strictly advisory:** LLM output is parsed into structured Pydantic suggestions and can never mutate job state directly.
11. **Untrusted spreadsheet content:** Cell contents are treated as untrusted data and never interpolated into system prompts as instructions.
12. **Original file immutability:** Uploaded files are verified byte-identical before and after analyze, mapping, and processing.
13. **Formula injection neutralization:** All reformatted workbook string cells starting with `=`, `+`, `-`, `@`, `\t`, `\r` are prefixed with `'` while preserving native numeric types.
14. **Tenant isolation:** Requests for jobs belonging to other tenants return `HTTP 404` to prevent ID enumeration.

---

## 3. Database Schema (SQLite / PostgreSQL Compatible)

The job store is backed by SQLite (`shipflow.db`) with standard ANSI SQL for seamless PostgreSQL migration:

### `failsafe_jobs`
| Column | Type | Description |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUID job identifier |
| `status` | `TEXT` | `uploaded`, `needs_mapping`, `ready`, `processing`, `done`, `failed`, `expired` |
| `path` | `TEXT` | Absolute path to quarantined original upload |
| `output_path` | `TEXT` | Absolute path to generated reformatted workbook |
| `ext` | `TEXT` | `.xlsx` or `.csv` |
| `sheet_name` | `TEXT` | Active sheet name |
| `user_id` | `TEXT` | Uploading user ID |
| `tenant_id` | `TEXT` | Multi-tenant isolation ID |
| `column_count` | `INTEGER` | Detected column count |
| `analysis_json` | `TEXT` | Serialized `JobState` analysis |
| `mapping_json` | `TEXT` | Confirmed mapping dictionary |
| `mapping_source` | `TEXT` | `auto`, `user`, or `saved` |
| `created_at` | `REAL` | Epoch timestamp |
| `updated_at` | `REAL` | Epoch timestamp (used for atomic transitions & stuck job timeouts) |
| `expires_at` | `REAL` | Epoch TTL expiration timestamp |

### `failsafe_saved_mappings`
Stores position-aware column fingerprints: `hash(((col_idx, normalized_header)...) + col_count + tenant_id)`.
Allows recurring uploads from known carriers to auto-map safely without prompts.

### `failsafe_audit_logs`
Logs every action (`upload`, `auto`, `confirmed`, `cancelled`) with tenant ID, user ID, timestamp, and payload for full compliance traceability.

---

## 4. API Reference

All routes are mounted at root `/` and `/api/failsafe/`:

- `POST /jobs`: Upload spreadsheet file (`multipart/form-data`). Runs scan ingestion, computes confidence, matches saved layouts, and returns `JobState`.
- `GET /jobs/{id}`: Returns current `JobState` (enforces Tenant isolation via HTTP 404).
- `POST /jobs/{id}/mapping`: Submits user-confirmed column mapping (`MappingRequest`). Validates headers and transitions job to `ready`.
- `POST /jobs/{id}/cancel`: Aborts job and marks status as `expired` without modifying original file.
- `POST /jobs/{id}/process`: Quoting execution gate. Atomically transitions `ready` $\rightarrow$ `processing`, verifies full load limits, executes `run_agent()`, and sets `done`.
- `GET /jobs/{id}/download`: Downloads sanitized reformatted workbook (`.xlsx`).
- `GET /mappings`: Lists saved layout fingerprints for current tenant.
- `DELETE /mappings/{id}`: Deletes a saved layout fingerprint.
- `GET /failsafe/demo`: Interactive HTML/JS playground testing ambiguous sheets, skid modes, and conflict highlights.

---

## 5. Running Tests

Execute the complete failsafe test suite:
```bash
python -m pytest tests/test_detect.py tests/test_ingest.py tests/test_api.py tests/test_security.py tests/test_agent_adapter.py tests/test_modal_ui.py tests/test_hardening.py
```
Total coverage: 48 automated test cases covering edge cases, memory caps, zip bombs, formula injection, concurrent transitions, and contract invariants.
