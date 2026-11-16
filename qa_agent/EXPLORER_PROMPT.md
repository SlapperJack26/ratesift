# Antigravity `/browser` Exploratory QA Prompt

Use this prompt in an Antigravity chat session (with `/browser`) after running `python -m qa_agent.run` to perform an AI-driven exploratory pass over the local Quotelytics / Quotelytics site (`http://127.0.0.1:8000`).

---

## Guardrails (Mandatory)

1. **Browser-Only:** Interact with the application exclusively through the browser UI (`http://127.0.0.1:8000`). **Do not edit, create, or delete any project source code, templates, or database files.**
2. **Ephemeral Test Account:** Register a fresh Free Starter account on `/get-started` (`qa.explore.<timestamp>@quotelytics-qa.test`). Never log in as an administrator.
3. **Free-Tier Boundaries:** Stay within 3 rate sheets and 50 quotes (plus 1 deliberate over-limit test each).
4. **Denylist:** Never click Upgrade Tier, payment/trial buttons, or API key generation.
5. **Self-Cleanup:** At the end of your session, navigate to `/console/account` and click **Delete Account** so the test account and its data are purged.

## Exploratory Checklist

1. Read the latest `reports/<timestamp>/findings.json` to see what the deterministic Playwright suite already caught.
2. Explore visual layout, overlapping elements, confusing copy, modal focus traps, and edge-case inputs on:
   - Public pages: `/`, `/demo`, `/pricing`, `/privacy`, `/login`, `/get-started`, `/failsafe/demo`, `/flowchart`, `/showcase`
   - Authenticated Console: `/console/new-quote`, `/console/rate-sheets`, `/console/history`, `/console/account`, `/console/settings`
3. Append any new UX or functional findings (with screenshots) to the report.
