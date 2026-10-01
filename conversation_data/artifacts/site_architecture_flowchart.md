# Ratesift Page Architecture & Relation Flowchart

This document provides a comprehensive structural map of the **Ratesift** platform, organizing all 9 views into **Public Pages** and **Private (Authenticated) Pages**, with full transition logic and relationship mappings.

---

## 1. High-Level Architecture Flowchart

```mermaid
flowchart TD
    %% Public Domain
    subgraph PUBLIC["Public Pages (Light Theme • SEO Optimized • Public Nav)"]
        PUB_HOME["Home / Landing Page (public_landing_seo.html)"]
        PUB_DEMO["Interactive Demo (public_demo_view.html)"]
        PUB_PRICING["Pricing Page (public_pricing_view.html)"]
        PUB_LOGIN["Log In View (public_login_view.html)"]
        PUB_GET_STARTED["Get Started View (public_get_started_view.html)"]
    end

    %% Authentication Transition Gateway
    subgraph AUTH_GATE["Authentication Transition"]
        AUTH_ACTION{"Authentication Event: Login or Registration"}
    end

    %% Private Authenticated Domain
    subgraph PRIVATE["Private Pages (Authenticated Console • App Header)"]
        PRIV_NEW_QUOTE["New Rate Sheet Console (shipping_demo_view.html)"]
        PRIV_HISTORY["Quotes History (quotes_view.html)"]
        PRIV_ACCOUNT["Account Settings (account_settings_view.html)"]
        PRIV_SETTINGS["System & Quoting Settings (settings_view.html)"]
    end

    %% Design Showcase & Dev Tooling
    subgraph SHOWCASE["Design System Hub"]
        SHOWCASE_HUB["Master Showcase (showcase_all_views.html)"]
    end

    %% Public Navigation Relations
    PUB_HOME <-->|Top Nav Bar| PUB_DEMO
    PUB_HOME <-->|Top Nav Bar| PUB_PRICING
    PUB_DEMO <-->|Top Nav Bar| PUB_PRICING

    PUB_HOME -->|'Log in' button| PUB_LOGIN
    PUB_DEMO -->|'Log in' button| PUB_LOGIN
    PUB_PRICING -->|'Log in' button| PUB_LOGIN

    PUB_HOME -->|'Get Started' CTA / Nav| PUB_GET_STARTED
    PUB_DEMO -->|'Get Started' CTA / Nav| PUB_GET_STARTED
    PUB_PRICING -->|'Start Free' CTA / Nav| PUB_GET_STARTED

    PUB_LOGIN <-->|'Need account?' / 'Have account?'| PUB_GET_STARTED

    %% Entry into Authenticated Session
    PUB_LOGIN -->|Credentials Validated| AUTH_ACTION
    PUB_GET_STARTED -->|Account Created| AUTH_ACTION
    AUTH_ACTION -->|Redirects to Default Landing| PRIV_NEW_QUOTE

    %% Private Navigation Relations
    PRIV_NEW_QUOTE <-->|Header Tabs| PRIV_HISTORY
    PRIV_NEW_QUOTE -->|'Process ->' Batch Quote| PRIV_HISTORY

    %% User Profile Dropdown Transitions
    PRIV_NEW_QUOTE -.->|User Dropdown: Account| PRIV_ACCOUNT
    PRIV_NEW_QUOTE -.->|User Dropdown: Settings| PRIV_SETTINGS
    PRIV_HISTORY -.->|User Dropdown: Account| PRIV_ACCOUNT
    PRIV_HISTORY -.->|User Dropdown: Settings| PRIV_SETTINGS

    PRIV_ACCOUNT <-->|Settings Switcher| PRIV_SETTINGS
    PRIV_ACCOUNT -->|Header Nav| PRIV_NEW_QUOTE
    PRIV_SETTINGS -->|Header Nav| PRIV_NEW_QUOTE

    %% Sign Out Transition
    PRIV_ACCOUNT -.->|User Dropdown: Sign Out| PUB_HOME
    PRIV_SETTINGS -.->|User Dropdown: Sign Out| PUB_HOME
    PRIV_NEW_QUOTE -.->|User Dropdown: Sign Out| PUB_HOME
    PRIV_HISTORY -.->|User Dropdown: Sign Out| PUB_HOME

    %% Showcase Interconnections
    SHOWCASE_HUB -.->|Previews All Views| PUBLIC
    SHOWCASE_HUB -.->|Previews All Views| PRIVATE
```

---

## 2. Page Classification & Relations Breakdown

### A. Public Pages (Accessible to All Users & Crawlers)

All public pages share a unified header (SF Logo, Home/Demo/Pricing menu, Log in, Get Started) and footer (SF Logo, Docs, Support, API, Privacy, Date):

| Page | File | Purpose | Primary Outbound Relations |
| :--- | :--- | :--- | :--- |
| **Home / Landing** | [public_landing_seo.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_landing_seo.html) | Brand introduction, SEO indexing, key value propositions, quoting engine workflow. | • `Demo`<br/>• `Pricing`<br/>• `Log in`<br/>• `Get Started` |
| **Demo** | [public_demo_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_demo_view.html) | Live interactive preview with sample rate sheets (Parcels, Pallets, Medical) without signing up. | • `Home`<br/>• `Pricing`<br/>• `Log in`<br/>• `Get Started (CTA)` |
| **Pricing** | [public_pricing_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_pricing_view.html) | 4 tiers: Free Starter ($0), Broker Pro ($49), Broker Team ($149), Business (Custom). Monthly/Annual toggle. | • `Home`<br/>• `Demo`<br/>• `Get Started (Free Tier)`<br/>• `Log in` |
| **Log In** | [public_login_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_login_view.html) | Single centered credential entry with 1-click `Auto-fill Alex Rivers`. | • `Get Started (Switch)`<br/>• Redirects to `New Rate Sheet` upon login |
| **Get Started** | [public_get_started_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/public_get_started_view.html) | Dedicated single centered account creation box with origin ZIP and 1-click test setup. | • `Log in (Switch)`<br/>• Redirects to `New Rate Sheet` upon account creation |

---

### B. Private Pages (Authenticated User Console)

Private pages use the authenticated console header with **SF Logo**, **New Quote**, **History**, and the **User Dropdown (`Alex R. ˅`)**:

| Page | File | Purpose | Primary Outbound Relations |
| :--- | :--- | :--- | :--- |
| **New Rate Sheet** | [shipping_demo_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/shipping_demo_view.html) | Core application engine: upload `.xlsx`/`.xls`, preview parsed columns, click `Process →`. | • `Quotes History`<br/>• Dropdown: `Account`<br/>• Dropdown: `Settings`<br/>• Dropdown: `Sign out` |
| **Quotes History** | [quotes_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/quotes_view.html) | Data warehouse of generated quotes, search by Quote ID, sort by rates, Excel cell tracking. | • `New Rate Sheet`<br/>• Dropdown: `Account`<br/>• Dropdown: `Settings`<br/>• Dropdown: `Sign out` |
| **Account Settings** | [account_settings_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/account_settings_view.html) | Profile management for Alex Rivers, TechCorp Logistics, default origin ZIP `94103`. | • `System Settings`<br/>• `New Rate Sheet`<br/>• `Quotes History`<br/>• `Sign out` |
| **System Settings** | [settings_view.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/settings_view.html) | Quote engine rules (USD, lbs, +10% markup, auto-header detection, empty row skipper). | • `Account Settings`<br/>• `New Rate Sheet`<br/>• `Quotes History`<br/>• `Sign out` |

---

### C. Design Showcase & Review Hub

* **[showcase_all_views.html](file:///C:/Users/Dylan/.gemini/antigravity/brain/b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4/showcase_all_views.html)**:
  * Unified side-by-side presentation tool featuring **2x2 Grid View**, **Horizontal Strip**, and **Live Interactive Tabs (1 through 9)**.
  * Links directly into every public and private screen for review.
