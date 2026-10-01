# Ratesift Full-Stack SaaS Implementation Plan

This implementation plan transitions **Ratesift** from validated UI prototypes and design specifications into a production-grade, secure, and scalable web application.

---

## 1. System Goals & Scope Boundaries

* **Core Function:** High-speed batch shipping rate calculation directly from uploaded Excel files (`.xlsx`, `.xls`).
* **Strict Scope Boundary:** Quoting engine only. **No** label generation, **no** carrier booking workflows, **no** tracking number generation.
* **Tier Model Enforcement:**
  * **Free Starter:** 1 uploaded rate sheet, capped at 50 quotes/month for real data validation.
  * **Broker Pro ($49/mo):** 5 rate sheets, 1,000 quotes/month.
  * **Broker Team ($149/mo):** 20 rate sheets, 5,000 quotes/month, multi-seat.
  * **Business (Custom):** Unlimited sheets, custom quote volumes, Embedded Quoting API.
* **Design Standards Compliance:**
  * Public vs. Private domain segregation.
  * Zero sales bubbles, zero dark code terminals.
  * Tables: Bold headers (`font-bold`), unbolded cells (`font-normal`), zero highlight badges, exact spreadsheet coordinate tracking (`Sheet 1 • Row 14, Col C`).

---

## 2. Recommended Technology Stack

| Layer | Recommended Technology | Justification |
| :--- | :--- | :--- |
| **Framework & Fullstack** | **Next.js 15 (App Router, TypeScript)** | Unified SSR for public SEO pages + client-side interactivity for authenticated console. |
| **Styling & Design Tokens** | **Tailwind CSS v4** | Directly ports all prototype HTML/CSS with exact color tokens and accessibility styling. |
| **Excel Parsing Engine** | **`exceljs` + `xlsx` (SheetJS)** | High-throughput memory-efficient parsing preserving exact sheet and cell coordinates. |
| **Database & ORM** | **PostgreSQL + Prisma ORM** | Relational integrity for user tiers, quote history, line-item coordinates, and system settings. |
| **Authentication & AuthZ** | **Auth.js (NextAuth) or Supabase Auth** | Session-based cookies, role-based access control, route protection middleware. |
| **File Storage** | **S3-compatible object storage (or local disk in dev)** | Secure, isolated spreadsheet upload storage with encrypted data-at-rest. |
| **API Architecture** | **REST + OpenAPI Spec (Zod validated)** | Powers both internal frontend requests and the Business Tier Embedded Quoting API. |

---

## 3. Phased Implementation Roadmap

### Phase 1: Project Scaffolding & Layout Architecture
- [x] Initialized workspace repository with Python/FastAPI backend, Tailwind CSS UI engine, and OpenPyXL parsing.
- [x] Established clean modular directory structure (`templates/public`, `templates/console`, `services/`, `sample_sheets/`).
- [x] Ported and normalized all 11 view templates with seamless REST routing (`/`, `/demo`, `/pricing`, `/login`, `/get-started`, `/console/new-quote`, `/console/history`, `/console/account`, `/console/settings`, `/flowchart`, `/showcase`).
- [x] Integrated Public Domain Header and Footer with full accessibility and SEO landmarks.
- [x] Integrated Console Header with SF Logo, tab switches, and User Profile Dropdown (`AR Alex R. ˅`).
- [x] Generated realistic sample `.xlsx` rate sheets for parcels, pallets, and medical cargo.
- [x] Built and passed automated route and backend engine test suites (`test_engine.py` and `test_server_startup.py`).

---

### Phase 2: Database Schema & Authentication Gateway
- [x] Defined and migrated relational database schema with subscription tiers, users, settings, sessions, quote batches, and quote items.
- [x] Implemented Subscription Tiers: Free Starter (1 sheet, 50 quotes/month), Broker Pro, Broker Team, and Business.
- [x] Implemented Route Guarding Gateway: Unauthenticated requests to `/console/*` automatically redirect to `/login?next=...` (HTTP 303).
- [x] Implemented Cookie Sessions & Authentication: `/api/auth/login` and `/api/auth/register` set HTTP-only 30-day session cookies.
- [x] Implemented Quota Enforcement: Monthly quotes and sheet volume validation in `/api/user/quota` and `/api/quotes/upload`.
- [x] Connected frontend Login and Get Started forms to real backend authentication endpoints with dynamic feedback.
- [x] Connected console user dropdown "Sign out" actions to `/api/auth/logout`.
- [x] Built and passed automated Phase 2 test suite (`test_phase2_auth_quota.py`).

---

### Phase 3: Excel Parsing Engine & Cell Coordinate Mapper
- [x] Developed `parser_service.py` with OpenPyXL supporting `.xlsx` and `.xls` uploads.
- [x] Automated header detection and dynamic column mapping (Origin, Destination, Weight, Service).
- [x] Extracted exact coordinate metadata for every line item (e.g. `Sheet 1 • Row 14, Col C`).
- [x] Connected **New Rate Sheet** view (`new_quote.html`) dropzone with live file selection, progress spinner, and calculation trigger.

---

### Phase 4: Multi-Carrier Quoting & Markup Calculation Engine
- [x] Implemented `rating_service.py` with multi-carrier rate matrix (FedEx, UPS, Estes Express, USPS, R+L Carriers).
- [x] Applied dynamic broker markup percentage (+10% default, customizable via System Settings).
- [x] Enforced subscription tier quotas: Free Starter tier rejection (HTTP 403) when 1 rate sheet limit is exceeded, unlocking on Broker Pro/Team.

---

### Phase 5: Quotes History Warehouse & Excel Export
- [x] Wired **Quotes History** view (`history.html`) to live database quotes with exact spreadsheet cell coordinates.
- [x] Implemented client-side and server-side real-time search by Quote ID and carrier.
- [x] Implemented sorting by rate (`Sort by Rate ˅`: High to Low, Low to High, and Reset).
- [x] Built downloadable Excel Export endpoint (`GET /api/quotes/export`) streaming formatted `.xlsx` workbooks.

---

### Phase 6: Account & System Settings Synchronization
- [x] Connected **Account Settings** view (`account.html`) to `POST /api/user/account/update` and `GET /api/user/profile`.
- [x] Connected **System Settings** view (`settings.html`) to `POST /api/settings/update` (Currency, Units, Markup %, parser toggles).
- [x] Verified dynamic application of user settings to subsequent rate calculations.

---

### Phase 7: Embedded Quoting API (Business Tier)
- [x] Implemented API Key authentication mechanism (`api_keys` table and `X-API-Key` validation).
- [x] Built REST endpoint `POST /api/v1/quotes/batch` returning structured sub-second rate calculations for 3PLs/brokers.
- [x] Interactive OpenAPI (Swagger) documentation generated at `/docs`.

---

### Phase 8: Testing, SEO Audit, and Verification
- [x] **Automated Test Suites:**
  * `test_engine.py`: Core database, parser, rating, and auth unit tests (PASSED).
  * `test_server_startup.py`: Route and template delivery integration tests (PASSED).
  * `test_phase2_auth_quota.py`: Authentication, sessions, route guarding, and quota tests (PASSED).
  * `test_full_platform_e2e.py`: Complete multi-phase platform end-to-end verification (ALL PASSED).
- [x] Verified accessibility landmarks, SEO meta tags, skip links, and light theme design rules.

---

### Phase 9: Responsive Auto-Scaling & Device Viewport System
- [x] Implemented fluid auto-scaling containers across all 11 view templates (`w-full max-w-5xl lg:max-w-6xl xl:max-w-7xl 2xl:max-w-[1400px] mx-auto`).
- [x] Added viewport meta tag with `maximum-scale=5.0` for accessible mobile pinch-zoom support.
- [x] Built mobile navigation hamburger drawer (`<nav id="mobile-nav-drawer">`) for viewports `< 768px` across all public pages.
- [x] Enforced strict touch-friendly table containment (`overflow-x-auto` with `-webkit-overflow-scrolling: touch;`) for quotes warehouse and sandbox tables.
- [x] Preserved all core design rules: Single centered card on `/login` and `/get-started`, zero sales bubbles, zero tracking numbers, light theme only.
- [x] Added interactive Device Viewport Switcher Toolbar in `/showcase` (Phone 390px, iPad/Tablet 768px, Laptop 1024px, Desktop Monitor 100% Fluid) with scale zoom controls (100%, 90%, 80%, 75%).
- [x] Synchronized all responsive updates into brain artifacts directory.
- [x] Verified zero regressions across all 4 automated test suites.

---

## 4. Status: All Implementation Phases Complete & Verified

The ShipFlow platform is fully scaffolded, wired, verified, and running in `c:\Users\Dylan\Documents\antigravity\quick-hertz`. The live application server is active on `http://127.0.0.1:8000`.
