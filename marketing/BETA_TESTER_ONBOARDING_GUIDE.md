# PRIVATE BETA TESTER ONBOARDING & FEEDBACK GUIDE
### Quotelytics Inc. — 15-Minute Broker Onboarding Playbook
*Target Beta Period: November 2 – November 27, 2026 • Target: 5–10 Canadian Freight Brokers*

---

## 1. PRE-CALL PREPARATION CHECKLIST
Before hopping on the call / screen-share with a beta broker:
* [ ] Verify the broker's account is provisioned or have their signup link ready (`https://quotelytics.ca/get-started`).
* [ ] Request that the broker has **1 real carrier Excel tariff (.xlsx or .csv)** ready on their desktop (e.g. Day & Ross, Manitoulin, Midland, Maritime-Ontario, or Bison).
* [ ] Have your test demo link open as backup: `https://quotelytics.ca/demo`.

---

## 2. THE 15-MINUTE ONBOARDING SCRIPT

### Phase 1: Context & Problem Alignment (Minutes 0–3)
> *"Thanks for taking the time, {{name}}. As you know, we built Quotelytics because Canadian dispatchers are spending hours every week manually calculating CWT breaks, deficit thresholds, and fuel surcharges across multiple spreadsheets."*
> 
> *"Our goal today is simple: take one of your real carrier rate sheets, upload it, and produce an instant ranked quote in under 60 seconds so you can see if the math matches what you calculate by hand."*

---

### Phase 2: Live Sheet Upload & Human Confirmation Gate (Minutes 3–7)
1. **Screen-share:** Guide the broker to `https://quotelytics.ca/console/rate-sheets`.
2. **Drag & Drop:** Have them drag their Excel file into the upload zone.
3. **The Confirmation Gate:**
   > *"Notice how the system auto-detects your columns: Origin FSA, Destination FSA, Min Floor, and weight breaks (L5C, M5C, M1M, etc.). You can inspect the cell coordinates right here before confirming."*
4. Click **Confirm & Ingest**.

---

### Phase 3: Quoting & Mathematical Verification (Minutes 7–11)
1. Navigate to **New Quote** (`/console/new-quote`).
2. Have the broker input a lane they quote frequently:
   * Origin: (e.g., `M5V 2T6` or `TORONTO, ON`)
   * Destination: (e.g., `T2P 1J9` or `CALGARY, AB`)
   * Weight: (e.g., `1,850 lbs`)
3. Click **Calculate Rates**.
4. **Inspect Results:**
   > *"Here are all your eligible carriers ranked lowest to highest. Notice how it itemizes base rate, fuel surcharge, and net quote."*
5. **Open Audit Drawer:**
   > *"Click on the quote. Look at this: 'Sheet 1 • Row 18, Column D'. Every dollar is mathematically mapped back to the exact cell in your original spreadsheet. No AI hallucinations, no guesses."*
6. **Demonstrate 1-Click Client Proposal:**
   > *"Toggle on a 15% brokerage markup, click 'Export Client Proposal PDF', and you have a polished quote sheet ready to send to your shipper."*

---

## 3. FEEDBACK DISCOVERY QUESTIONS (Minutes 11–15)

Ask these exact questions and take notes:

1. **On Accuracy & Math:**
   * *"Does this rate match what you or your dispatchers would have calculated by hand for this lane?"*
   * *"Did the deficit rating break at the threshold you expected?"*

2. **On Tariff Formats:**
   * *"Are there any complex accessorials or footnote rules in your other tariffs (like beyond charges or tailgate rules) that we should test next?"*

3. **On Workflow & Time Savings:**
   * *"If your team had this for all 5–10 of your primary carriers, how much time would this save your desk each day?"*

4. **On Pricing & Value (Pre-Selling the $79 Pro Tier):**
   * *"When we launch paid accounts on December 1st at $79 CAD/month, would this be an easy return on investment for your brokerage?"*

---

## 4. TESTIMONIAL CAPTURE SCRIPT

If the broker expresses enthusiasm during the session, immediately ask:
> *"{{Name}}, that means a lot. Would you mind if I quoted you on that for our website? Something like: '[Quote about saving 15 minutes per quote]' — {{Name}}, Operations Manager at {{Company}}?"*

*Record the quote in `marketing/TESTIMONIALS_BETA.md` for launch day!*
