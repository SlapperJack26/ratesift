# RateSift — Automated Freight & Shipping Rate Comparison Platform

RateSift is a modern SaaS platform designed for Canadian freight brokers, forwarders, and 3PLs to ingest carrier Excel rate cards (`.xlsx`, `.xls`, `.csv`), calculate deterministic quotes across CWT breaks and accessorials, and rank competing carrier options side-by-side.

> **Strict Scope Boundary:** The platform **only quotes and compares rates**; it strictly **does not handle booking, tracking numbers, or label generation**. Data is resident in Canada with zero third-party rate sharing.

---

## Quick Start

### 1. Requirements
* Python 3.9+ with `fastapi`, `uvicorn`, `pandas`, `openpyxl`, `python-multipart`.

### 2. Run the Application
```bash
python run.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## Application Views & Routing

### Public Domain (SEO-Optimized & Crawlable)
* `GET /` — **Home / Landing Page** (Value propositions, features, FAQ schema).
* `GET /demo` — **Interactive Demo** (Sample rate sheets, live batch simulation).
* `GET /pricing` — **Pricing Plans** (Free Starter, Broker Pro, Broker Team, Business Custom).
* `GET /login` — **Log In Screen** (Single centered card, 1-click test fill for Alex Rivers).
* `GET /get-started` — **Get Started Screen** (Single centered account creation card).

### Private Domain (Authenticated Console)
* `GET /console/new-quote` — **New Rate Sheet Console** (Upload Excel, map columns, click `Process →`).
* `GET /console/history` — **Quotes History Warehouse** (Search quote ID, sort by rate, exact cell coordinates `Sheet 1 • Row 14, Col C`).
* `GET /console/account` — **Account Settings** (Alex Rivers / TechCorp Logistics, default origin `94103`).
* `GET /console/settings` — **System Settings** (Currency USD, Units lbs, Markup +10%, parser toggles).

### Architecture & Showcase Hub
* `GET /flowchart` — **Interactive Architecture Flowchart** (Visual map of public vs. private relationships).
* `GET /showcase` — **Master Design Showcase** (2x2 Grid, Horizontal Strip, 10 Live Tabs).
* `GET /docs` — **Interactive OpenAPI (Swagger) Documentation** (Embedded Quoting API for Business tier).

---

## Design System Enforcement
* **Tables:** Headers are always **bold** (`font-bold`), data cells are **unbolded** (`font-normal`), with **zero highlight badges** or colored status pills.
* **Cell Coordinate Tracking:** Every quoted item references its exact spreadsheet cell coordinate (e.g., `Sheet 1 • Row 14, Col C`).
* **Pricing & Marketing:** Zero floating sales bubbles, badges, or dark terminal code blocks.
* **Auth Focus:** Single centered box on both Login and Get Started pages.
