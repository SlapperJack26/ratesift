# STATUTORY SECURITY BREACH REGISTER & AUDIT LOG
### Quotelytics Inc. — Statutory 24-Month PIPEDA §10.3 Compliance Record
*Governing Standard: Personal Information Protection and Electronic Documents Act (PIPEDA) & Breach of Security Safeguards Regulations (SOR/2018-64)*

---

> [!IMPORTANT]
> **Statutory Obligation:** Under PIPEDA Section 10.3, Quotelytics Inc. must record and maintain details of **every breach of security safeguards** for a minimum period of **twenty-four (24) months** from the date the breach was determined to have occurred. This record must be made available to the Privacy Commissioner of Canada upon request.

---

## 1. Summary Registry of Security Incidents

| Incident Reference | Date Discovered | Category of Incident | Systems Involved | RROSH Threshold Met? | OPC Notified? | Status | Minimum Retention Until |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| *Example: INC-2026-001* | *2026-10-15* | *Failed Brute Force Lockout* | *Auth Gateway (/api/auth/login)* | *No (Mitigated by 429 Rate Limiter)* | *No* | *Closed* | *2028-10-15* |
| **INC-[YYYY]-[SEQ]** | *[YYYY-MM-DD]* | *[Category]* | *[System/Table]* | *[Yes / No]* | *[Yes / No]* | *[Open/Closed]* | *[Date + 24 Months]* |

---

## 2. Detailed Incident Incident Record Template

*Copy and complete the template below for every breach or suspected security safeguard failure:*

```markdown
### INCIDENT REPORT: [INC-YYYY-SEQ]

#### 1. Discovery & Incident Details
* **Incident ID:** INC-202__-_____
* **Date & Time Discovered:** YYYY-MM-DD HH:MM EST
* **Date & Time Occurred (or estimated range):** YYYY-MM-DD to YYYY-MM-DD
* **Discovered By:** [Staff Member / Automated Monitoring Alert / Customer Report]
* **Lead Investigator / Privacy Officer:** Dylan, Privacy Officer (privacy@quotelytics.ca)

#### 2. Nature & Circumstances of the Breach
* **Incident Description:** [Describe exactly what occurred, how unauthorized access occurred, or how safeguards were compromised.]
* **Type of Information Involved:**
  [ ] Account Credentials / Passwords (Argon2id hashed)
  [ ] Tenant Negotiated Carrier Tariffs / Rate Matrices
  [ ] Historical Quote Inquiries & Postal Routing
  [ ] Customer Business Contact Data (Name, Email, Phone, Company)
  [ ] Payment Details (Note: Stripe-hosted SAQ-A; no raw card numbers stored)
* **Estimated Number of Affected Accounts / Individuals:** [Number]

#### 3. Real Risk of Significant Harm (RROSH) Assessment
* **Sensitivity Analysis:** [Assess sensitivity of affected records.]
* **Probability of Misuse:** [Assess whether data was encrypted, intercepted, or published.]
* **Harm Assessment:** [Evaluate risk of financial loss, business reputation damage, or identity theft.]
* **Final RROSH Determination:** [ ] YES — Meets RROSH   [ ] NO — Does not meet RROSH
* **Rationale for Determination:** [Provide reasoned justification.]

#### 4. Containment & Remediation Actions Taken
* **Immediate Containment:** [e.g., Session tokens revoked, firewall rules updated, API keys invalidated.]
* **Date Containment Completed:** YYYY-MM-DD HH:MM EST
* **System Hardening:** [e.g., Code patch deployed, additional rate limits added.]

#### 5. Statutory Notifications (If RROSH Met)
* **Office of the Privacy Commissioner (OPC) Notified:** [ ] Yes   [ ] No   [ ] Not Applicable
  * *Date OPC Report Submitted:* YYYY-MM-DD
  * *OPC File Reference Number:* [Insert Reference]
* **Affected Individuals Notified:** [ ] Yes   [ ] No   [ ] Not Applicable
  * *Date Individual Notifications Sent:* YYYY-MM-DD
  * *Notification Method:* Direct written email via verified account address
* **Other Entities Notified:** [e.g., Web Hosting Canada, Stripe, Law Enforcement]

#### 6. Sign-off & Statutory Retention
* **Incident Status:** [CLOSED / UNDER MONITORING]
* **Date Incident Formally Closed:** YYYY-MM-DD
* **Mandatory Statutory 24-Month Retention Date:** YYYY-MM-DD *(24 months from discovery)*
* **Privacy Officer Signature:** __________________________________
```

---

## 3. Annual Incident Review Log

*Reviewed annually by the Privacy Officer to evaluate recurring vectors and harden system safeguards:*

* **Year 2026 Review:** All security and privacy safeguards active. Salted Argon2id hashing, secure session cookies, tenant isolation, and sliding-window rate limiters confirmed active.
* **Year 2027 Review:** Scheduled for December 2027.
