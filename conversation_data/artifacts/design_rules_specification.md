# Ratesift Design System Specification: Public vs. Private Pages

This document outlines the strict design principles, component guidelines, layout rules, and scope boundaries governing the **Ratesift** platform across both **Public** and **Private (Authenticated)** views.

---

## 1. Universal Design Foundations

These core guidelines apply across **every page** in the application:

* **Theme & Light Mode:**
  * Clean, high-contrast, modern light theme using Tailwind CSS (`bg-white`, `bg-slate-50`, `text-slate-900`, `text-slate-500`).
  * Pure white container cards (`bg-white`) bordered by subtle slate boundaries (`border border-slate-200`) and soft shadows (`shadow-xs` / `shadow-sm`).
* **Brand Identity & Visual Logo:**
  * **Header & Footer:** Uses the official visual brand logo image (`RateSift` with red rounded filter icon and subtitle "Shipping rate comparison") across all top headers (`h-8 md:h-9`) and footers (`h-6 md:h-7`).
  * **Everywhere Else:** Spelled with standard punctuation and proper noun capitalization as **Ratesift** (headings, body copy, pricing cards, FAQs, `<title>`, `<meta>`, Schema JSON-LD, and exported files).
  * **Primary Action Color:** Crimson Red (`bg-red-600`, hover: `bg-red-700`).
* **Strict Scope Boundary:**
  * **Quoting Only:** The platform exclusively calculates batch rate quotes from Excel spreadsheets (`.xlsx`, `.xls`).
  * **Strictly Prohibited:** No booking workflows, no label generation, no shipping manifests, and no tracking number generation.
* **Persistent Footer Specification:**
  * **Left:** Visual RateSift logo image + 4 crawlable links: `Documentation`, `Support`, `API`, `Privacy`.
  * **Right:** Current date stamp: `September 28, 2026`.

---

## 2. Public Pages Design Rules

**Target Views:** [Home](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_landing_seo.html), [Demo](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_demo_view.html), [Pricing](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_pricing_view.html), [Log In](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_login_view.html), [Get Started](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_get_started_view.html).

### A. Navigation & Header
* **Three-Zone Public Header:**
  * **Left:** Brand logo and name (`SF SHIPFLOW`).
  * **Center:** Crawlable main menu (`Home`, `Demo`, `Pricing`).
  * **Right:** Secondary text link `Log in`, primary conversion button `Get Started` (blue button with focus ring).
* Active page marked semantically with `aria-current="page"`.

### B. Aesthetic & Content Prohibitions
* **Zero Sales Bubbles:** No colored pill badges, floating labels, "Best Value", or "Most Popular" floating tags on pricing tiers or cards.
* **Zero Dark Code Terminals:** No black terminal code blocks in marketing sections. Technical details are presented in clean architectural capability cards.
* **Single Element Focus on Auth Screens:** 
  * The [Log In](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_login_view.html) and [Get Started](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_get_started_view.html) pages must feature **only the centered form box** between the header and footer (no multi-column marketing sidebars or distracting testimonials).
* **1-Click Test Access:** Interactive `Auto-fill Alex Rivers` buttons to allow instant friction-free testing of the login/registration transitions.

### C. SEO & Accessibility Standards
* **Semantic Landmarks:** Every public page must employ `<header role="banner">`, `<nav role="navigation">`, `<main id="main-content" role="main">`, and `<footer role="contentinfo">`.
* **Skip Link:** Accessible invisible-until-focused skip link (`href="#main-content"`).
* **Meta Tags:** Canonical URL, OpenGraph cards, Twitter cards, robots meta, and JSON-LD structured data (`WebPage`, `BreadcrumbList`, `FAQPage`, `SoftwareApplication`).

---

## 3. Private Pages Design Rules (Authenticated Console)

**Target Views:** [New Rate Sheet](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/shipping_demo_view.html), [Quotes History](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/quotes_view.html), [Account Settings](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/account_settings_view.html), [System Settings](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/settings_view.html).

### A. Navigation & Header
* **Console Header Structure:**
  * **Left:** Brand mark (`SF SHIPFLOW`) linking directly to the console home (`New Rate Sheet`).
  * **Center:** Primary app switcher tabs: `New Quote` and `History`. The active tab is indicated with an active state pill/underline.
  * **Right:** User profile dropdown trigger (`AR Alex R. ˅`).
* **User Profile Dropdown Menu:**
  * Header showing user avatar, name (`Alex Rivers`), and company (`TechCorp Logistics`).
  * Navigation links: `Account` (routes to `account_settings_view.html`), `Settings` (routes to `settings_view.html`).
  * Exit link: `Sign out` (terminates session and redirects to `public_landing_seo.html`).

### B. Strict Data & Table Display Rules
* **Header Row:** Must be **bold** (`font-bold`, `text-slate-800`).
* **Data Cells:** Must be **unbolded** (`font-normal`, `text-slate-600` / `font-mono text-slate-700`).
* **Zero Highlight Badges in Tables:** Absolutely no colored pills, green/yellow/red status bubbles, or pill tags in table cells. Values must be rendered as clean text.
* **Spreadsheet Coordinate Tracking:** When presenting rate outputs, the platform must display exact cell coordinates mapping back to the user's Excel file (e.g., `Sheet 1 • Row 14, Col C`).
* **Monospace Numeric Data:** Currency, weights, dimensions, and ZIP codes must use clean monospace typography (`font-mono`) for columnar alignment.

### C. Standardized Terminology & Actions
* **Console View Titles:** 
  * Main Title: `New rate sheet` (not "Shipments", not "Bookings").
  * **Routing Headers (Vertical Layout):**
    * **`From` Header (Origin):** Stacked vertically with 4 horizontal input fields: `City Name`, `Province / State`, `Postal Code / Zip Code`, and `Country` (dropdown list).
    * **`To` Header (Destination):** Stacked vertically directly below `From`, with 4 horizontal input fields: `City Name`, `Province / State`, `Postal Code / Zip Code`, and `Country` (dropdown list).
  * Primary Action Button: `Process →` (triggers batch rate calculation from spreadsheet or routing parameters).
* **Quotes History Actions:**
  * Search Input: Placeholder `Search quote ID...`.
  * Sort Controls: Dropdown `Sort by Rate ˅`.

### D. Default Business Logic & Profile State
* **Default User:** Alex Rivers, Freight Brokerage Specialist.
* **Default Organization:** TechCorp Logistics.
* **Default Origin:** 1200 Market St, San Francisco, CA `94103`.
* **Quoting Defaults:** Currency `USD ($)`, Units `Imperial (lbs)`, Global Broker Markup `+10%`, Auto-detect header `Active`, Skip blank rows `Active`.

---

## 4. Side-by-Side Comparison Matrix

| Design Element | Public Pages | Private Console Pages |
| :--- | :--- | :--- |
| **Primary Goal** | Education, conversion, validation, SEO indexation. | High-speed spreadsheet parsing and rate lookup. |
| **Header Center** | `Home` • `Demo` • `Pricing` | `New Quote` • `History` |
| **Header Right** | `Log in` (link) + `Get Started` (button) | User Avatar Dropdown (`AR Alex R. ˅`) |
| **Form Layout** | Single centered card, zero clutter. | Multi-column workspace (Dropzone + Parser + Rates). |
| **Tables** | Bold headers, unbolded cells, sample tags. | **Bold headers, unbolded cells, zero highlight badges, exact Excel cell coordinates**. |
| **Terminology** | "Automated Excel Quoting", "Validate Real Data" | `New rate sheet`, `Get Quote`, `Process →` |
| **Exit / Nav Out** | Link into Log in / Get Started. | Dropdown `Sign out` (redirects to Public Home). |
