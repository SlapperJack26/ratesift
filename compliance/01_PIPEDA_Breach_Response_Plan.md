# PIPEDA PRIVACY & SECURITY BREACH RESPONSE PLAN
### Quotelytics Inc. — Corporate Governance & Regulatory Compliance Manual
*Effective Date: October 2026 • Governing Law: PIPEDA (Canada) • Jurisdiction: Ontario, Canada*

---

## 1. PURPOSE & STATUTORY MANDATE

This **Privacy Breach Response Plan** establishes the mandatory procedures to be followed by **Quotelytics Inc.** ("Quotelytics", the "Corporation") in the event of an actual, suspected, or threatened breach of security safeguards involving personal information or confidential tenant data.

This plan is enacted pursuant to the *Personal Information Protection and Electronic Documents Act* (S.C. 2000, c. 5, "**PIPEDA**"), specifically:
* **Section 10.1:** Mandatory notification to the Privacy Commissioner of Canada;
* **Section 10.2:** Mandatory notification to affected individuals and tenant organizations; and
* **Section 10.3:** Statutory obligation to maintain a record of **every breach of security safeguards** for a minimum of **twenty-four (24) months**.

---

## 2. DESIGNATED PRIVACY OFFICER & INCIDENT TEAM

* **Designated Privacy Officer:** Dylan ([FOUNDER / PRIVACY OFFICER])
* **Official Compliance Contact:** `privacy@quotelytics.ca` / `support@quotelytics.ca`
* **Emergency Dispatch Hotline:** 289-929-8565
* **Registered Office:** Ontario, Canada
* **Hosting Infrastructure:** Web Hosting Canada (WHC) — Montreal, QC & Halifax, NS

The Privacy Officer possesses primary authority to lead breach response, assess risk, coordinate forensic investigation, and execute statutory filings with the Office of the Privacy Commissioner of Canada (OPC).

---

## 3. FOUR-STEP INCIDENT RESPONSE PROTOCOL

Whenever an unauthorized access, disclosure, loss, or acquisition of data occurs, the Corporation executes the following four-stage response:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     STEP 1      │ ──> │     STEP 2      │ ──> │     STEP 3      │ ──> │     STEP 4      │
│   CONTAINMENT   │     │  ASSESSMENT     │     │  NOTIFICATION   │     │   PREVENTION    │
│  & Preservation │     │  (RROSH Test)   │     │   (OPC & Users) │     │  & Hardening    │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

### STEP 1: Immediate Containment & Evidence Preservation
*Goal: Stop the unauthorized exposure immediately while preserving forensic logs.*
1. **Isolate Compromised Accounts:** Revoke active session tokens (`quotelytics_session`) and revoke any compromised single-use auth tokens in `auth_tokens`.
2. **Access Revocation:** If an API key is implicated, immediately disable the affected `ql_live_` key in the database.
3. **Infrastructure Isolation:** If server compromise is suspected on the WHC Cloud VPS:
   * Block malicious IP addresses via `ufw` or `fail2ban`.
   * Rotate environment secrets (`SESSION_SECRET`, `STRIPE_WEBHOOK_SECRET`, SMTP credentials) in `/srv/quotelytics/app/.env`.
   * Restart the FastAPI application service (`systemctl restart quotelytics`).
4. **Preserve Forensic Evidence:** Capture and archive `journald` system logs, Nginx access logs (`/var/log/nginx/access.log`), SQLite WAL files, and database query logs without altering timestamps.

---

### STEP 2: Risk Assessment & The RROSH Test
*Goal: Determine if the incident poses a "Real Risk of Significant Harm" to any individual.*

Under PIPEDA Section 10.1(1), notification to the OPC and individuals is legally mandatory if it is reasonable in the circumstances to believe that the breach creates a **Real Risk of Significant Harm ("RROSH")**.

#### Assessment Factors:
1. **Sensitivity of the Information:**
   * High Sensitivity: Unsalted passwords, financial credentials, SINs, or highly confidential customer pricing agreements.
   * Moderate Sensitivity: Negotiated carrier freight tariffs, CWT discount matrices, customer shipping addresses.
   * Low Sensitivity: Publicly available business contact cards.
   * *Note: Passwords in Quotelytics are hashed with salted Argon2id, significantly mitigating credential exposure risk.*
2. **Probability of Misuse:**
   * Was the data encrypted in transit (TLS 1.3) and at rest?
   * Was the breach targeted (malicious exfiltration) or accidental (sent to wrong email)?
   * Has the data been published or weaponized by an adversary?
3. **Potential Harm:**
   * Bodily harm, humiliation, damage to reputation or relationships, loss of employment, business or professional opportunities, financial loss, identity theft, or negative effects on credit rating.

**Determination:** The Privacy Officer documents the formal RROSH determination in writing in the Statutory Breach Register (`compliance/02_Statutory_Breach_Log_Register.md`).

---

### STEP 3: Mandatory Statutory Notifications
If RROSH is determined (or voluntarily as a trust measure for enterprise clients):

#### A. Notification to the Privacy Commissioner of Canada (OPC)
* **Timeline:** File as soon as feasible after determining that a breach occurred.
* **Method:** Submit the formal [OPC Privacy Breach Report Form](https://www.priv.gc.ca/en/report-a-concern/report-a-privacy-breach-at-your-organization/).
* **Mandatory Contents:**
  * Description of the circumstances and cause of the breach.
  * Date or time period of the breach.
  * Description of the personal/commercial information involved.
  * Estimate of the number of individuals affected.
  * Description of steps taken to contain the breach and reduce risk of harm.
  * Description of steps taken to notify affected individuals.
  * Contact details of the Quotelytics Privacy Officer.

#### B. Notification to Affected Individuals / Tenant Brokerages
* **Timeline:** As soon as feasible after breach confirmation.
* **Delivery:** Direct written electronic notice to the verified email on file.
* **Notice Contents:**
  * Plain-language description of what occurred.
  * Specific categories of information involved (e.g., uploaded rate sheets, account email).
  * Measures Quotelytics has taken to contain and remediate the incident.
  * Recommended steps the customer can take to protect themselves (e.g., password reset, reviewing active API keys).
  * Contact information for Quotelytics Support and the OPC.

---

### STEP 4: Prevention & System Hardening
Following containment:
1. Conduct a root-cause engineering post-mortem.
2. Implement automated regression tests (e.g., in `tests/`) replicating the exploit vector.
3. Apply required code or infrastructure patches.
4. Review and update this response plan annually.

---

## 4. STATUTORY 24-MONTH RECORD-KEEPING OBLIGATION

Under PIPEDA Section 10.3 and the *Breach of Security Safeguards Regulations* (SOR/2018-64):
* **Every breach of security safeguards must be recorded.**
* This applies to **all** incidents, including low-risk, contained, or accidental breaches that did **not** meet the RROSH threshold.
* The Corporation must maintain each incident record for a minimum of **24 months** from the date the breach was discovered.
* Records must be produced upon demand to the Privacy Commissioner of Canada during an audit or inquiry.

All records are maintained in [`compliance/02_Statutory_Breach_Log_Register.md`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/compliance/02_Statutory_Breach_Log_Register.md).
