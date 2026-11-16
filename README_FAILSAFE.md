# Rate-Sheet Header Failsafe + Excel Formatting Agent

> **Failsafe Contract:** A wrong quote is worse than a pause. When in doubt, the agent stops and asks the user to map the columns manually. It must never guess silently on required fields.

---

## 1. System Overview & Architecture

Quotelytics allows freight brokers to upload carrier rate sheets (`.xlsx`, `.csv`). The **Rate-Sheet Header Failsafe** intercepts every spreadsheet, performs deep structural inspections, detects pricing modes, computes confidence scores, and gates processing until column assignments are 100% verified.

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

The job store is backed by SQLite (`quotelytics.db`) with standard ANSI SQL for seamless PostgreSQL migration:

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

### `failsafe_audit_logs` (Append-Only Trigger Protected)
Logs every rate sheet confirmation (`confirmed`) with tenant ID, sheet SHA-256 hash, timestamps, and structured mapping summary. Prohibits UPDATE and DELETE operations via SQLite triggers (`trg_failsafe_audit_prevent_update`, `trg_failsafe_audit_prevent_delete`). Excludes PII and unvalidated free-text.

### `failsafe_override_attributions` (PIPEDA Detachable)
Stores human override attributions, user IDs, client IP addresses, and user-provided notes. Detachable under PIPEDA/GDPR right-to-be-forgotten without violating audit log immutability.

### `failsafe_shadow_logs`
Records shadow-mode evaluations when `FAILSAFE_MODE="shadow"`, logging blocker and warning findings for post-hoc analysis without blocking live brokerage operations.

### `failsafe_rejection_counters`
Tracks validation rejections per tenant and client IP to power rolling anomaly detection. Pruned every 7 calendar days.

### `system_settings`
Key-value store for platform deployment governance, tenant allowlists (`failsafe_tenant_allowlist`), deploy timestamp (`failsafe_deploy_timestamp`), and immutable sunset timestamp (`failsafe_sunset_timestamp`).

---

## 4. API Reference

All routes are mounted at root `/` and `/api/failsafe/`:

- `POST /jobs`: Upload spreadsheet file (`multipart/form-data`). Runs scan ingestion, computes confidence, matches saved layouts, and returns `JobState`.
- `GET /jobs/{id}`: Returns current `JobState` (enforces Tenant isolation via HTTP 404).
- `POST /jobs/{id}/dry-run`: Ephemeral zero-database preview calculation engine. Executes in-memory canonical math with cooperative 3.0s deadline and monotonic `seq_id` race guard.
- `POST /jobs/{id}/mapping`: Submits user-confirmed column mapping (`MappingRequest`). Evaluates blockers and warnings, logs shadow/audit records, and transitions job.
- `POST /jobs/{id}/cancel`: Aborts job and marks status as `expired` without modifying original file.
- `POST /jobs/{id}/process`: Quoting execution gate. Atomically transitions `ready` $\rightarrow$ `processing`, verifies full load limits, executes `run_agent()`, and sets `done`.
- `GET /jobs/{id}/download`: Downloads sanitized reformatted workbook (`.xlsx`).
- `GET /mappings`: Lists saved layout fingerprints for current tenant.
- `DELETE /mappings/{id}`: Deletes a saved layout fingerprint.
- `GET /failsafe/demo`: Interactive HTML/JS playground testing ambiguous sheets, skid modes, and conflict highlights.

---

## 5. Operational Governance & Releases (v6.2)

### Tri-State Governance Modes (`FAILSAFE_MODE`)
- `FAILSAFE_MODE="off"`: Legacy mode; validation checks disabled.
- `FAILSAFE_MODE="shadow"`: Validates in background and logs to `failsafe_shadow_logs`; never blocks confirmation (fails open).
- `FAILSAFE_MODE="enforce"`: Hard enforcement; blockers reject with HTTP 422 (`E_BLOCKER_VIOLATION`); unacknowledged warnings reject with HTTP 409 (`E_UNACKNOWLEDGED_WARNING`). Allowlisted pilot tenants can be enforced while global mode remains in shadow.

### Database Backup & Archival Migration
```bash
python scripts/backup_and_migrate_release_2b.py
```
1. Verifies free disk space $\ge 2.5\times$ DB+WAL on backup target and temp directory.
2. Performs atomic `VACUUM INTO` backup.
3. Verifies `PRAGMA integrity_check;` and table-by-table row count matching.
4. Transactionally archives all legacy parcel rate sheets (`is_legacy_parcel = 1`, `confirmation_status = 'ARCHIVED'`).

---

## 6. Running Tests

Execute the complete 50-scenario Failsafe and LTL transition verification suite:
```bash
pytest tests/test_failsafe_release_0_and_1a.py tests/test_failsafe_release_1b.py tests/test_failsafe_release_2a.py tests/test_failsafe_release_2b.py -v
```

Execute the full platform test suite (119 automated test scenarios):
```bash
pytest tests/test_failsafe_*.py tests/test_weight_cwt_golden.py tests/test_skid_based_ltl_rating.py tests/test_skid_failsafe_tier_rating.py tests/test_milestone*.py -q
```
