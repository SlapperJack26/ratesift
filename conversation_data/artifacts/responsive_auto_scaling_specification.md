# Ratesift Responsive Auto-Scaling & Edge-to-Edge Margin System

## 1. Overview & Objectives
The Ratesift platform is built with **full-bleed edge-to-edge margin alignment and fluid auto-scaling across four standard screen limit categories** while **strictly maintaining all original design rules**:
- **Header & Footer Margins:** Always inline with the top and bottom of the screen respectively (`m-0` top for header, `m-0 mt-auto` bottom for footer, `min-h-screen flex flex-col justify-between w-full`).
- **Horizontal Margins:** Always inline with the left and right edges of the screen (`w-full`, zero outer container margins/paddings on all screen sizes).
- **Mobile Phones** (`< 640px`, e.g., 360px - 480px)
- **iPads & Tablets** (`640px - 1024px`, e.g., 768px portrait, 820px iPad Air)
- **Laptops & Small Displays** (`1024px - 1440px`, e.g., 1280px MacBook Air, 1366px laptop)
- **Desktop Monitors & Ultrawides** (`> 1440px`, e.g., 1920x1080 Full HD, 1440p 2K, 4K)

---

## 2. Strict Design Rule Preservation Matrix

| Design Rule | Implementation Guarantee |
| :--- | :--- |
| **Edge-to-Edge Margins** | Header margin inline with top of screen (0px gap), Footer margin inline with bottom of screen (0px gap), Horizontal margins inline with left/right of screen (0px gap) on all views and screen sizes. |
| **Strict Quoting Only** | Zero carrier booking buttons, zero label generation, zero delivery tracking numbers across all responsive breakpoints. |
| **Clean Light Theme** | Maintained across all resolutions: `#ffffff` background, `#e2e8f0` border, `bg-slate-50/50` cards. No dark code blocks or dark overlays. |
| **Single Centered Card** | On `/login` and `/get-started`, the single authentication/registration box is the **only element** between header and footer (`max-w-md w-full mx-auto`). |
| **Zero Sales Bubbles** | Pricing cards retain identical clean borders (`border-slate-200`) without highlight badges, ribbons, or "Popular" sales pills. |
| **Strict Table Rules** | Bold table column headers (`font-bold`), unbolded data rows (`font-normal`), exact coordinate cell references (`Sheet 1 • Row 14, Col C`), and touch-scrollable horizontal containment (`overflow-x-auto`). |

---

## 3. Responsive Auto-Scaling Architecture by Device Limit

### 📱 1. Mobile Phones (`< 640px` • 360px – 480px)
* **Header Collapse & Hamburger Drawer:** On viewports under `768px`, the absolute centered navigation collapses into a dedicated mobile drawer toggle button (`md:hidden`). Tapping the button expands `<nav id="mobile-nav-drawer">` with accessible touch targets for Home, Demo, Pricing, Log In, and Get Started.
* **Hero & Typography Scaling:** Primary headlines scale smoothly from `text-3xl` down to `text-2xl` with fluid line-height to avoid awkward word breaks.
* **Form & Button Stacking:** Hero action buttons (`flex flex-col sm:flex-row`) and console filter bars stack vertically into comfortable tap targets (`min-h-[44px]`).
* **Table Touch Scrolling:** Historical quotes table and demo preview tables are encapsulated in `-webkit-overflow-scrolling: touch; overflow-x-auto;` containers, preventing layout blowouts while keeping all spreadsheet coordinates intact.

### 📟 2. iPads & Tablets (`640px` – `1024px` • 768px Portrait, 820px, 1024px Landscape)
* **Header Unfurl:** Main navigation links become visible and centered (`md:flex absolute inset-x-0 mx-auto`) with balanced spacing (`gap-6 lg:gap-8`).
* **Adaptive Grids:**
  * Feature pillars switch from 1 column to 2/3 columns (`grid-cols-1 sm:grid-cols-2 md:grid-cols-3`).
  * Pricing plans adapt to 2x2 grid on portrait tablets (`md:grid-cols-2 lg:grid-cols-4`).
* **Console Workspace:** New Rate Sheet drag-and-drop zone and manual origin form render comfortably side-by-side.

### 💻 3. Laptops (`1024px` – `1440px`)
* **Standard Container:** Scales fluidly up to `lg:max-w-6xl mx-auto`.
* **4-Tier Pricing Display:** Full horizontal side-by-side comparison of Free Starter, Broker Pro, Broker Team, and Business API tiers.
* **Full Data Warehouse:** Historical quotes table displays all 6 columns simultaneously without requiring horizontal scroll on 13" and 15" screens.

### 🖥️ 4. Desktop Monitors & 4K (`> 1440px`)
* **Fluid Container Ceiling:** Outer wrapper smoothly expands to `xl:max-w-7xl 2xl:max-w-[1400px] mx-auto` while remaining gracefully centered.
* **Centered Single-Card Constraint:** Login and Get Started cards maintain strict `max-w-md mx-auto` constraints, preventing awkward card stretching across wide monitors.

---

## 4. Interactive Device Viewport Switcher in Showcase

The **Showcase Suite** at `/showcase` now features a dedicated **Device Viewport & Auto-Scaling Controls Toolbar**:
1. **Device Presets:**
   - 📱 **Phone** (390 × 844 px — iPhone 14/15 frame with bezel)
   - 📟 **iPad / Tablet** (768 × 1024 px — iPad frame)
   - 💻 **Laptop** (1024 × 768 px — 13" laptop frame)
   - 🖥️ **Desktop** (100% Fluid monitor)
2. **Zoom / Scale Selector:** `100%`, `90%`, `80%`, `75%` scaling with `transform-origin: top center` so tablet and laptop viewports fit on any screen.
3. **Live Indicator Badge:** Real-time feedback displaying the simulated screen width and height.
4. **All 10 Live Screens Switchable:**
   - 1. New Rate Sheet (`/console/new-quote`)
   - 2. Quotes History (`/console/history`)
   - 3. Account Settings (`/console/account`)
   - 4. Quoting Rules (`/console/settings`)
   - 5. Home Landing (`/`)
   - 6. Interactive Demo (`/demo`)
   - 7. Pricing Plans (`/pricing`)
   - 8. Login Page (`/login`)
   - 9. Get Started (`/get-started`)
   - 10. Architecture Flowchart (`/flowchart`)

---

## 5. Verification & Test Suite Status
All four test suites pass with 100% assertions:
1. `test_engine.py`: **[PASS]** OpenPyXL coordinate extraction, rate calculations (+10% markup), and user profile verification.
2. `test_phase2_auth_quota.py`: **[PASS]** Route guarding, session issuance, quota enforcement, and registration.
3. `test_server_startup.py`: **[PASS]** All 8 core HTTP endpoints return status 200 with expected body content.
4. `test_full_platform_e2e.py`: **[PASS]** Complete 8-phase end-to-end integration across all public and console workflows.
