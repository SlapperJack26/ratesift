# RateSift Agent — Rules & Implementation Plan

This document serves as the master specification and operational template for the **RateSift Agent**.

---

## 1. The 36 Agent Rules

### Reading and parsing rate sheets
1. **Explicit extraction only & Dynamic Classification:** Only extract values that are explicitly present in the sheet. Never guess, infer or fill in a missing rate, zone or weight break. Autonomously detect table headers at arbitrary row positions using currency prerequisites and continuous row density weighting.
2. **Normalized schema:** Convert every sheet into the normalized schema (carrier, service, zone, weight break, base rate, surcharges, minimum charge, dimensional weight rule, effective and expiry dates) before any quote is calculated.
3. **Source traceability:** Record the source of every extracted value (file name, sheet tab, cell or row) so any number can be traced back to the original.
4. **Footnotes, hidden data, and accessorials:** Read notes, footnotes and hidden rows or columns, since surcharges, exclusions and conditions are often buried there. Parse multi-row descriptions and nested footnote conditions completely.
5. **Unit and currency detection:** Detect and record the currency, weight unit (lb or kg) and dimension unit (in or cm) for every sheet. Never assume them.
6. **Needs review flagging & prose ambiguity:** Flag any cell, column, or rule you are not confident you interpreted correctly (including ambiguous numbers inside sentences), and mark it "needs review" instead of using it silently.
7. **Human confirmation gate & Confusion Gate:** Require a human to confirm each newly parsed sheet before it is used for live quotes. When competing header candidates score within 10% confidence, halt and present a rich preview (sample headers, candidate row numbers, and 2–3 rows of underlying data) for user confirmation.

### Calculating quotes
8. **Deterministic pricing:** Calculate every quote with deterministic code and the confirmed data. Never estimate a price with language-model reasoning.
9. **Dimensional weight rules:** Calculate dimensional weight using the carrier's own divisor and rules, and bill on the greater of actual weight and dimensional weight.
10. **Carrier zone resolution:** Resolve the origin and destination to the carrier's zone using that carrier's own zone mapping, not a generic one.
11. **Conditional surcharges:** Apply surcharges only when their conditions are met (residential, liftgate, fuel, remote area), and list each one separately.
12. **Minimum charge comparison:** Compare the calculated total to the carrier's minimum charge and use whichever is higher.
13. **Full breakdown transparency:** Always show the base rate, each surcharge and the final total. Never show a bare total.
14. **Deterministic consistency:** Give the same inputs against the same data the same result every time.
15. **Final-step rounding:** Round only at the final step, and follow each sheet's own rounding rules if it states them.

### Filtering and validity
16. **Effective date filtering:** Exclude any sheet that is expired or not yet effective for the shipment date, and warn the user that it was excluded.
17. **Version precedence:** When two versions of the same carrier's sheet exist, use the newest valid one.
18. **Operational limits:** Exclude carriers or services that cannot handle the shipment (lane not served, weight or size over the limit, mode mismatch), and explain why.
19. **Confirmation enforcement:** Never quote a rate from a sheet that has not passed the confirmation step.

### Ranking and output
20. **Multi-tier ranking:** Rank by lowest total price by default, with transit time as the first tie-breaker and the user's preferred carrier as the second.
21. **In-memory re-sorting:** Let the user re-sort the same results by fastest transit, best value or cost per unit without recalculating.
22. **Comprehensive comparison:** Show every valid option, not only the winner, so the user can compare.
23. **Flagged data indicators:** Clearly label any option that depends on flagged or low-confidence data.

### Honesty and error handling
24. **Truth in availability:** If no valid rate can be found, say so plainly and state the reason. Never return a made-up or approximate price.
25. **Missing detail prompting:** If required shipment details are missing (weight, dimensions, postal code), ask for them instead of assuming.
26. **Non-binding disclaimer:** Never present a quote as a binding offer from a carrier. It is a calculation from the user's own uploaded rate data.
27. **Rate shift alerts:** When a rate changes sharply from the previous version of a sheet (for example over 25%), flag it for the user to verify.

### Data handling and privacy
28. **Customer data confidentiality:** Treat uploaded rate sheets as confidential customer data. Never share one customer's rates with another or use them to inform another customer's results.
29. **Canadian residency (WHC):** Use uploaded data only to serve the account that uploaded it, and keep it stored in Canada, in line with the WHC hosting plan.
30. **Complete audit logging:** Keep a log of every quote (inputs, sheets used, result) so any quote can be audited later.

### Communication
31. **Freight broker terminology:** Use plain, professional language that freight brokers will recognize, without unnecessary jargon.
32. **Concise answers:** Keep answers short by default and offer the full breakdown on request.

### Document-Trained Structure Recognition & Layout Quarantine (Word Doc Rules)
33. **7-Category Spreadsheet Classification:** Classify every non-rate row into one of 7 standardized categories: Rate Table Header, Rate Matrix Data Row, Non-Critical Company Info/Letterhead, Non-Critical Legal Disclaimer/Terms, Operational Accessorial Rule, Metadata/Reference Row, or Decorative Noise.
34. **Letterhead Exclusion:** Never ingest company letterhead, contact details, account numbers, or address footers as shipping lanes or rate columns.
35. **Disclaimer Quarantine:** Quarantine legal disclaimers, boilerplate terms, and E&OE statements away from numerical rate matrices; preserve them in the audit trail without allowing them to break rating pipelines.
36. **Prose Surcharge Extraction:** Extract accessorial and surcharge pricing embedded in prose notes into a structured surcharge ledger; never inject prose descriptions into numeric rate grids.

---

## 2. Training Corpus & Format Ingestion Engine (50 Distinct Templates)

To guarantee the agent handles real-world freight broker complexity, the system is calibrated against a **50-template benchmark corpus** (detailed in [`RATE_SHEET_50_TEMPLATES_CORPUS.md`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/RATE_SHEET_50_TEMPLATES_CORPUS.md)).

- **Guide Template #1 (Day & Ross Canadian LTL/PTL Tariff):** Used as the primary calibration guide for multi-table layout parsing, textual accessorial extraction (29 terms, conditional exceptions, ferry surcharge tiers, density rules), CWT weight breaks, and PTL flat rates.
- **Templates 02–50:** Covers SMC3 CzarLite, postal code FSA-to-zone grids (Purolator, Canpar, Canada Post), multiweight parcel (FedEx/UPS), Canadian & US regional LTL (Manitoulin, Midland, Kindersley, Polaris, ODFL, R+L, SAIA, Estes), reefer & heated logistics (Erb), domestic & cross-border intermodal rail (CN, CPKC, Maritime-Ontario), port drayage (Vancouver, Montreal), ocean FCL/LCL, air freight chargeable weight, heavy-haul, flatbed mileage, and final-mile white glove.

---

## 3. Technical Implementation Roadmap

```
Milestone 0: 50-Format Rate Sheet Training Corpus & Layout Classifier (Template #1 Day & Ross Guide + 49 Industry Formats)
Milestone 1: Normalized Database & Multi-Tenant Schema (Rules 2, 3, 28, 29, 30)
Milestone 2: Deep Extraction & Confirmation Gate UI (Rules 1, 4, 5, 6, 7, 19, 33-36)
Milestone 3: Deterministic Quoting Engine (Rules 8, 9, 10, 11, 12, 14, 15)
Milestone 4: Filtering, Versioning & Anomaly Engine (Rules 16, 17, 18, 27)
Milestone 5: Broker UI & In-Memory Re-Sorting (Rules 13, 20, 21, 22, 23, 26, 31, 32)
Milestone 6: Verification & End-to-End Automated Test Suite (Rules 1–36)
```

