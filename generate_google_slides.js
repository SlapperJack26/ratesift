/**
 * generate_google_slides.js
 * ============================================================================
 * Google Apps Script to automatically generate the complete 18-Slide
 * RateSift Platform & Business Plan Presentation directly in Google Slides.
 * 
 * HOW TO USE IN GOOGLE SLIDES:
 * 1. Open Google Drive (https://drive.google.com) or Google Slides.
 * 2. Go to https://script.google.com and click "New project".
 * 3. Replace the Code.gs editor content with this entire file.
 * 4. Click the "Run" button (select createRateSiftPresentation).
 * 5. Grant permissions if prompted.
 * 6. Check the Execution log for the link to your brand new Google Slides presentation!
 * ============================================================================
 */

function createRateSiftPresentation() {
  var presentationTitle = "RateSift — Automated Freight Platform & 2026 Business Plan";
  var deck = SlidesApp.create(presentationTitle);
  var slides = deck.getSlides();
  
  // Remove default blank slide
  if (slides.length > 0) {
    slides[0].remove();
  }

  // Brand Colors
  var RED_PRIMARY = "#DC2626";
  var RED_DARK    = "#991B1B";
  var RED_LIGHT   = "#FEF2F2";
  var SLATE_DARK  = "#0F172A";
  var SLATE_NAVY  = "#1E293B";
  var SLATE_MUTED = "#64748B";
  var SLATE_LIGHT = "#F8FAFC";
  var BORDER_COL  = "#E2E8F0";
  var WHITE       = "#FFFFFF";
  var INDIGO      = "#4F46E5";
  var EMERALD     = "#059669";

  // Helper function to create standard header banner
  function addHeader(slide, titleText, categoryText, slideNumStr) {
    // Category pill
    var pill = slide.insertShape(SlidesApp.ShapeType.ROUND_RECTANGLE, 50, 20, 220, 24);
    pill.getFill().setSolidFill(RED_LIGHT);
    pill.getBorder().getLineFill().setSolidFill("#FECACA");
    pill.getBorder().setWeight(1);
    var pPill = pill.getText().setText(categoryText.toUpperCase());
    pPill.getTextStyle().setFontSize(9).setBold(true).setForegroundColor(RED_PRIMARY);

    // Title
    var titleBox = slide.insertTextBox(titleText, 50, 48, 580, 50);
    titleBox.getText().getTextStyle().setFontSize(18).setBold(true).setForegroundColor(SLATE_DARK);

    // Slide Number
    var numBox = slide.insertTextBox(slideNumStr, 640, 24, 50, 24);
    numBox.getText().getTextStyle().setFontSize(10).setBold(true).setForegroundColor(SLATE_MUTED);

    // Divider
    var line = slide.insertShape(SlidesApp.ShapeType.RECTANGLE, 50, 96, 620, 1.5);
    line.getFill().setSolidFill(BORDER_COL);
    line.getBorder().setTransparent();
  }

  // Helper to add card container
  function addCard(slide, x, y, w, h, title, bullets, accentColor) {
    var card = slide.insertShape(SlidesApp.ShapeType.ROUND_RECTANGLE, x, y, w, h);
    card.getFill().setSolidFill(SLATE_LIGHT);
    card.getBorder().getLineFill().setSolidFill(BORDER_COL);
    card.getBorder().setWeight(1);

    var accent = slide.insertShape(SlidesApp.ShapeType.ROUND_RECTANGLE, x + 1, y + 1, w - 2, 5);
    accent.getFill().setSolidFill(accentColor || RED_PRIMARY);
    accent.getBorder().setTransparent();

    var tb = slide.insertTextBox("", x + 12, y + 12, w - 24, h - 24);
    var tf = tb.getText();
    tf.setText(title + "\n\n");
    tf.getParagraphs()[0].getTextStyle().setFontSize(13).setBold(true).setForegroundColor(SLATE_DARK);

    bullets.forEach(function(b) {
      var p = tf.appendParagraph("• " + b.label + ": " + b.text);
      p.getTextStyle().setFontSize(9.5).setForegroundColor(SLATE_MUTED);
    });
  }

  // --------------------------------------------------------------------------
  // SLIDE 1: Title Slide
  // --------------------------------------------------------------------------
  var s1 = deck.appendSlide();
  var bg1 = s1.insertShape(SlidesApp.ShapeType.RECTANGLE, 0, 0, 720, 405);
  bg1.getFill().setSolidFill(SLATE_DARK);
  bg1.getBorder().setTransparent();

  var card1 = s1.insertShape(SlidesApp.ShapeType.ROUND_RECTANGLE, 45, 45, 630, 315);
  card1.getFill().setSolidFill(SLATE_NAVY);
  card1.getBorder().getLineFill().setSolidFill("#334155");

  var b1 = s1.insertShape(SlidesApp.ShapeType.ROUND_RECTANGLE, 75, 75, 260, 24);
  b1.getFill().setSolidFill("#450A0A");
  b1.getBorder().getLineFill().setSolidFill(RED_PRIMARY);
  b1.getText().setText("CANADIAN FREIGHT & LOGISTICS RATING SAAS").getTextStyle().setFontSize(8.5).setBold(true).setForegroundColor("#FECACA");

  var tb1 = s1.insertTextBox("", 75, 120, 560, 160);
  var t1 = tb1.getText();
  t1.setText("RateSift Platform Overview & 2026 Business Plan\n");
  t1.getParagraphs()[0].getTextStyle().setFontSize(26).setBold(true).setForegroundColor(WHITE);

  var p1_2 = t1.appendParagraph("Automated Spreadsheet Rating • 100% Deterministic Engine • Strict Zero-Booking Scope\n\n");
  p1_2.getTextStyle().setFontSize(13).setForegroundColor("#CBD5E1");

  var p1_3 = t1.appendParagraph("Prepared for: Executive Leadership & Investors • Hosted in Canada (WHC) • PIPEDA Compliant");
  p1_3.getTextStyle().setFontSize(10).setForegroundColor(SLATE_MUTED);

  s1.getNotesPage().getSpeakerNotesShape().getText().setText("Welcome everyone. Today we are presenting RateSift, an automated freight and shipping rate comparison platform designed specifically for Canadian freight brokers, forwarders, and 3PLs.");

  // --------------------------------------------------------------------------
  // SLIDE 2: Executive Summary
  // --------------------------------------------------------------------------
  var s2 = deck.appendSlide();
  addHeader(s2, "Executive Summary: The Freight Quoting Bottleneck", "Platform Foundation", "02/18");
  addCard(s2, 50, 115, 195, 265, "1. The Broker Problem", [
    {label: "Disparate Tariffs", text: "Brokers manage dozens of carrier rate cards in differing Excel layouts."},
    {label: "Manual Cell Hunting", text: "Looking up rates and breaks takes 15–20 minutes per quote."},
    {label: "Error-Prone Markups", text: "Risk of underquoting or missing accessorial surcharges."},
    {label: "Bloated TMS Tools", text: "Legacy software costs $30k–$80k/yr and locks brokers in."}
  ], RED_PRIMARY);
  addCard(s2, 260, 115, 195, 265, "2. The RateSift Solution", [
    {label: "Automated Ingestion", text: "Drag-and-drop any carrier Excel spreadsheet; auto-normalizes breaks."},
    {label: "100% Deterministic", text: "Pure Python calculation math—zero LLM hallucinations."},
    {label: "Cell Traceability", text: "Every quoted rate records its exact origin cell coordinate."},
    {label: "1-Click Proposals", text: "Generates branded customer quotes with broker margins."}
  ], EMERALD);
  addCard(s2, 470, 115, 195, 265, "3. Strict Scope Boundary", [
    {label: "Quoting Focus", text: "RateSift strictly focuses on rating math and carrier comparisons."},
    {label: "NO Label Printing", text: "Zero shipping label generation or thermal printer overhead."},
    {label: "NO Booking Workflows", text: "Does not handle carrier dispatch booking or tendering."},
    {label: "NO Tracking Numbers", text: "Eliminates operational tracking baggage."}
  ], INDIGO);
  s2.getNotesPage().getSpeakerNotesShape().getText().setText("The core opportunity in freight brokerage is unbundling rating intelligence from bloated legacy TMS software. Brokers waste hours daily cross-referencing multi-tab spreadsheets.");

  // --------------------------------------------------------------------------
  // SLIDE 3: Website Architecture
  // --------------------------------------------------------------------------
  var s3 = deck.appendSlide();
  addHeader(s3, "Website Architecture: Public vs. Authenticated Segregation", "Page Architecture", "03/18");
  addCard(s3, 50, 115, 195, 265, "Public Domain (5 Views)", [
    {label: "Home (/)", text: "Crawlable SEO hub, value propositions, FAQ schema."},
    {label: "Demo (/demo)", text: "Live sandbox with parcel, pallet, and medical rate sheets."},
    {label: "Pricing (/pricing)", text: "4-tier commercial plans with annual discount switch."},
    {label: "Log In (/login)", text: "Single centered card with 1-click Alex Rivers auto-fill."},
    {label: "Get Started", text: "Frictionless registration provisioning Free Starter."}
  ], RED_PRIMARY);
  addCard(s3, 260, 115, 195, 265, "Console (5 Views)", [
    {label: "New Quote", text: "Broker rater with FSA lookup and live carrier ranking."},
    {label: "Carrier Tariffs", text: "Rate sheet warehouse and Human Confirmation Gate."},
    {label: "Quotes History", text: "Audit log warehouse with RS-YYYYMMDD codes."},
    {label: "Account (/account)", text: "Broker profile, origin hub, and subscription status."},
    {label: "Settings", text: "Default markup (+10%), CAD/USD, and fuel index toggles."}
  ], EMERALD);
  addCard(s3, 470, 115, 195, 265, "Showcase & APIs", [
    {label: "Flowchart (/flowchart)", text: "Interactive map of complete user routing."},
    {label: "Showcase (/showcase)", text: "Multi-device responsive testing toolbar."},
    {label: "Embedded API (/docs)", text: "OpenAPI Swagger docs for programmatic quoting."},
    {label: "Canadian Cloud", text: "All data resident in Canada (WHC / PIPEDA)."}
  ], INDIGO);

  // --------------------------------------------------------------------------
  // SLIDE 4: Public Home & Demo
  // --------------------------------------------------------------------------
  var s4 = deck.appendSlide();
  addHeader(s4, "Public Experience: High-Converting SEO & Interactive Demo", "Website Walkthrough", "04/18");
  addCard(s4, 50, 115, 300, 265, "Home / Landing Page ( GET / )", [
    {label: "Semantic SEO", text: "Optimized for Canadian freight rating and batch Excel calculator keywords."},
    {label: "Responsive Layout", text: "Fluid auto-scaling from 390px mobile screens to 1400px ultra-wide monitors."},
    {label: "Mobile Nav Drawer", text: "Collapsible navigation drawer ensuring seamless browsing on phones."},
    {label: "Schema.org Rich Data", text: "SoftwareApplication and FAQPage JSON-LD schemas embedded."},
    {label: "Clear CTAs", text: "Direct pathways to the live interactive demo or free registration."}
  ], RED_PRIMARY);
  addCard(s4, 370, 115, 300, 265, "Interactive Demo Sandbox ( GET /demo )", [
    {label: "Zero-Registration Sandbox", text: "Prospective clients evaluate calculation speed without creating an account."},
    {label: "Preloaded Tariffs", text: "Sample carrier sheets for Parcels, General Pallets, and Medical Cargo."},
    {label: "Interactive Sliders", text: "Live sliders for weight (100–10,000 lbs) and accessorial checkboxes."},
    {label: "Side-by-Side Ranking", text: "Instant price rankings comparing Day & Ross, Manitoulin, Midland, Bison."},
    {label: "Cell Coordinate Tracking", text: "Highlights exact row and column coordinate for every extracted rate."}
  ], INDIGO);

  // --------------------------------------------------------------------------
  // SLIDE 5: Public Pricing & Auth
  // --------------------------------------------------------------------------
  var s5 = deck.appendSlide();
  addHeader(s5, "Public Pages: Transparent Pricing & Distraction-Free Auth", "Website Walkthrough", "05/18");
  addCard(s5, 50, 115, 300, 265, "Pricing Page ( GET /pricing )", [
    {label: "4 Commercial Tiers", text: "Free Starter ($0), Broker Pro ($79 CAD/mo), Broker Team ($199), Business Custom."},
    {label: "Annual Discount Toggle", text: "Interactive switch calculates instant 20% annual discount across paid plans."},
    {label: "Capability Matrix", text: "Detailed comparison of active sheets, monthly quotas, and API access."},
    {label: "Embedded API Spotlight", text: "Outlines REST endpoints and sub-second SLAs for 3PL portal integrations."},
    {label: "Zero-Bloat Guarantee", text: "Clients never pay for unwanted label printing or carrier dispatch."}
  ], EMERALD);
  addCard(s5, 370, 115, 300, 265, "Auth Screens ( /login & /get-started )", [
    {label: "Single Centered Card", text: "Clean, distraction-free authentication form centered vertically."},
    {label: "1-Click Demo Auto-Fill", text: "Instant fill for Alex Rivers (Broker Specialist) enables seamless testing."},
    {label: "Secure 30-Day Sessions", text: "Issues HTTP-only, secure session cookies (ratesift_session)."},
    {label: "Frictionless Onboarding", text: "Registrations instantly provision Free Starter access (3 sheets / 50 quotes)."},
    {label: "Smart Gateway Routing", text: "Respects 'next' parameter to return brokers to their intended console screen."}
  ], SLATE_DARK);

  // --------------------------------------------------------------------------
  // SLIDE 6: Console Rater Cockpit
  // --------------------------------------------------------------------------
  var s6 = deck.appendSlide();
  addHeader(s6, "Console: Instant Freight Rater Cockpit ( /console/new-quote )", "Console Walkthrough", "06/18");
  addCard(s6, 50, 115, 300, 265, "The Broker's Quoting Center", [
    {label: "Canadian FSA Resolution", text: "Type any postal code (e.g. M5V 2T6) or city; resolves to normalized hubs."},
    {label: "Weight & Dimensions", text: "Handles actual vs. dimensional weight calculations with standard divisors."},
    {label: "Accessorial Checklist", text: "Tailgate/Liftgate, Appointment, Residential, and Heated Service."},
    {label: "Carrier Ranking Cards", text: "Ranked by lowest price with transit days, base rate, fuel, and final total."},
    {label: "In-Memory Re-Sorting", text: "Instant buttons: 'Lowest Price', 'Fastest Transit', 'Best Value' (0ms latency)."},
    {label: "Audit Accordion", text: "1-click expansion reveals CWT tier, minimum floor adjustments, and cells."}
  ], RED_PRIMARY);
  addCard(s6, 370, 115, 300, 265, "Workflow Efficiency Impact", [
    {label: "Sub-Second Quoting", text: "Calculates complex cross-provincial lanes in under 350 milliseconds."},
    {label: "Eliminates Human Error", text: "Automates hundredweight math, diesel fuel surcharges, and minimum floors."},
    {label: "Client-Side Speed", text: "Re-sorting happens in browser memory without waiting for server round-trips."},
    {label: "Integrated Tools", text: "Quick access to Rate Sheet Masker and 1-Click Client Proposal Generator."},
    {label: "Canadian Fleet Focus", text: "Calibrated against Day & Ross, Manitoulin, Midland, and Bison tariffs."}
  ], INDIGO);

  // --------------------------------------------------------------------------
  // SLIDE 7: Document Classifier
  // --------------------------------------------------------------------------
  var s7 = deck.appendSlide();
  addHeader(s7, "Console: Excel Ingestion & 7-Category Document Classifier", "Console Walkthrough", "07/18");
  addCard(s7, 50, 115, 195, 265, "1. Autonomous Dropzone", [
    {label: "Multi-Format Files", text: "Accepts .xlsx, .xls, and .csv rate cards from any major carrier."},
    {label: "Dynamic Header Scan", text: "Scans rows dynamically to detect table headers at arbitrary positions."},
    {label: "Unit & Currency", text: "Explicitly captures CAD/USD, lbs/kg, and in/cm without guessing."}
  ], RED_PRIMARY);
  addCard(s7, 260, 115, 195, 265, "2. 7-Category Classifier", [
    {label: "Rate Matrix Rows", text: "Ingested into normalized rate break tables for calculation."},
    {label: "Letterhead Exclusion", text: "Automatically quarantines carrier contact info and letterheads."},
    {label: "Disclaimer Isolation", text: "Isolates legal terms and boilerplate from numeric rating math."},
    {label: "Prose Accessorials", text: "Extracts surcharges embedded in descriptive text into ledgers."}
  ], INDIGO);
  addCard(s7, 470, 115, 195, 265, "3. Confirmation Gate", [
    {label: "Rule 7 & 19 Gate", text: "Newly uploaded sheets remain PENDING_REVIEW until confirmed."},
    {label: "Confusion Gate", text: "When candidate headers score within 10%, system halts for verification."},
    {label: "Rich Ingestion Preview", text: "Displays candidate headers and sample data rows for 1-click approval."}
  ], EMERALD);

  // --------------------------------------------------------------------------
  // SLIDE 8: Carrier Tariffs & Cell Coordinates
  // --------------------------------------------------------------------------
  var s8 = deck.appendSlide();
  addHeader(s8, "Console: Carrier Tariffs & Source Cell Coordinates", "Console Walkthrough", "08/18");
  addCard(s8, 50, 115, 300, 265, "Carrier Tariffs Library (/rate-sheets)", [
    {label: "Central Repository", text: "Manage active, pending, and archived rate cards across all contracted carriers."},
    {label: "Version Precedence", text: "Detects multiple revisions; uses the latest valid version automatically."},
    {label: "Effective Date Filter", text: "Excludes expired tariffs or future-dated rate sheets with broker warnings."},
    {label: "Tariff Status Badges", text: "Visual badges displaying CONFIRMED (ready for rating) or PENDING_REVIEW."},
    {label: "One-Click Re-Extraction", text: "Brokers can re-parse or review extracted accessorial rules on demand."}
  ], RED_PRIMARY);
  addCard(s8, 370, 115, 300, 265, "Cell-Level Traceability (Rule 3)", [
    {label: "Zero Black-Box Pricing", text: "Every extracted rate records its exact origin cell coordinate in the database."},
    {label: "Coordinate Notation", text: "Expressed as 'Sheet 1 • Row 14, Col C' or '[Tariff-2026] Rates!D12'."},
    {label: "Audit Defense", text: "When an accounting team questions a freight quote, cite the exact cell in seconds."},
    {label: "Coordinate Inspector", text: "Clicking any rate card allows brokers to inspect all underlying cell coordinates."},
    {label: "Data Residency Tag", text: "Every record is tagged with 'CA_CENTRAL_WHC' for PIPEDA compliance."}
  ], INDIGO);

  // --------------------------------------------------------------------------
  // SLIDE 9: Quotes History & Preferences
  // --------------------------------------------------------------------------
  var s9 = deck.appendSlide();
  addHeader(s9, "Console: Quotes History Warehouse & System Preferences", "Console Walkthrough", "09/18");
  addCard(s9, 50, 115, 300, 265, "Quotes History Warehouse (/history)", [
    {label: "Immutable Audit Trail", text: "Every calculation generates a unique, permanent audit ID (e.g. RS-20261001-A9F3)."},
    {label: "Real-Time Search", text: "Instant search by Quote ID, carrier name, origin city, or destination postal code."},
    {label: "Sort by Rate", text: "Interactive dropdown to sort archived quotes by total rate (High/Low)."},
    {label: "Coordinate Retention", text: "Historical records retain cell references and applied accessorial details."},
    {label: "Excel Workbook Export", text: "1-click 'Export to Excel' streams formatted .xlsx spreadsheets for accounting."}
  ], EMERALD);
  addCard(s9, 370, 115, 300, 265, "Account & Preferences (/settings)", [
    {label: "Dynamic Broker Markup", text: "Set default margin markups (e.g. +10% or +15%) applied to base freight."},
    {label: "Currency & Units", text: "Toggle between CAD and USD, and switch units between pounds (lbs) and kg."},
    {label: "Origin Dispatch Presets", text: "Configure default dispatch hubs (e.g. Toronto M5V 2T6) for quick quoting."},
    {label: "Fuel Index Integration", text: "Select diesel benchmark indices (OTA Standard, Atlantic, Western, Custom)."},
    {label: "Brokerage Branding", text: "Customize broker company name and dispatcher email on client proposals."}
  ], SLATE_DARK);

  // --------------------------------------------------------------------------
  // SLIDE 10: Deterministic Engine
  // --------------------------------------------------------------------------
  var s10 = deck.appendSlide();
  addHeader(s10, "Rating Intelligence: 100% Deterministic Engine (Zero AI Hallucinations)", "Functional Capabilities", "10/18");
  addCard(s10, 50, 115, 195, 265, "1. Pure Math Engine", [
    {label: "Rule 8 Compliance", text: "Pricing is calculated strictly by deterministic Python algorithms—no LLMs."},
    {label: "Rule 14 Idempotency", text: "Identical inputs against the same tariff always yield identical results."},
    {label: "Final-Step Rounding", text: "All intermediate math is preserved; half-up rounding occurs at the final step."}
  ], RED_PRIMARY);
  addCard(s10, 260, 115, 195, 265, "2. CWT & Minimums", [
    {label: "Hundredweight Scaling", text: "Calculates base freight: (Weight / 100) × CWT Rate across standard brackets."},
    {label: "Rule 12 Minimum Floors", text: "Compares calculated base charge against carrier minimum and bills higher."},
    {label: "Audit Transparency", text: "When a minimum floor applies, the log clearly flags 'min_charge_adjustment'."}
  ], INDIGO);
  addCard(s10, 470, 115, 195, 265, "3. Dimensional Weight", [
    {label: "Rule 9 Divisor Math", text: "Evaluates cubic dimensions using carrier divisors: (L × W × H) / 139."},
    {label: "PCF Density Rules", text: "Supports Pounds Per Cubic Foot (PCF) density rating for high-cube cargo."},
    {label: "Bill on Greater", text: "Engine compares actual scale weight vs. dim weight and bills on the greater."}
  ], EMERALD);

  // --------------------------------------------------------------------------
  // SLIDE 11: Canadian Postal FSA Resolver
  // --------------------------------------------------------------------------
  var s11 = deck.appendSlide();
  addHeader(s11, "Geographic Intelligence: Canadian Postal FSA Resolver", "Functional Capabilities", "11/18");
  addCard(s11, 50, 115, 300, 265, "1,600+ Canadian Postal FSAs Mapped", [
    {label: "Forward Sortation Area", text: "Resolves first 3 characters of any Canadian postal code to carrier terminals."},
    {label: "Downtown Hubs", text: "M5V 2T6 resolves to TORONTO, ON • H3B 1A1 resolves to MONTREAL, QC."},
    {label: "Western Hubs", text: "T2P 1J9 resolves to CALGARY, AB • V6B 2W9 resolves to VANCOUVER, BC."},
    {label: "Dorval Cargo Hub", text: "H9P 1K2 resolves to Dorval West Island terminal with regional drayage rules."},
    {label: "Rural Detection", text: "Flags remote or rural postal codes for carrier beyond-charge surcharges."}
  ], RED_PRIMARY);
  addCard(s11, 370, 115, 300, 265, "Lane Corridors & Carrier Zone Mapping", [
    {label: "Freight Corridors", text: "Automatically classifies lanes into standard corridors (ON-QC, ON-AB, BC-AB)."},
    {label: "Carrier Zones (Rule 10)", text: "Maps origins/destinations to each carrier's proprietary zone scheme."},
    {label: "Dedicated REST APIs", text: "Exposes GET /api/geo/resolve-fsa and /api/geo/resolve-lane for integrations."},
    {label: "Sub-Millisecond Speed", text: "In-memory indexed database delivers location resolution in under 2ms."},
    {label: "Validation (Rule 25)", text: "Rejects unresolvable postal codes with clear HTTP 400 validation prompts."}
  ], INDIGO);

  // --------------------------------------------------------------------------
  // SLIDE 12: SMC3 CzarLite & Deficit Rating
  // --------------------------------------------------------------------------
  var s12 = deck.appendSlide();
  addHeader(s12, "Pricing Optimization: SMC3 CzarLite & Deficit Weight Rating", "Functional Capabilities", "12/18");
  addCard(s12, 50, 115, 300, 265, "The Deficit Rating Principle", [
    {label: "The Freight Anomaly", text: "In standard CWT pricing, shipments near break thresholds can cost more."},
    {label: "Automated Bumping", text: "The engine tests if bumping shipment weight to the next bracket yields a lower price."},
    {label: "Real-World Example", text: "A shipment weighs 880 lbs on Toronto → Montreal:"},
    {label: "• Natural 5C Tier", text: "(880 / 100) × $42.00/CWT = $369.60 base charge."},
    {label: "• Deficit 1M Tier", text: "(1,000 / 100) × $34.00/CWT = $340.00 base charge."},
    {label: "Direct Savings", text: "Saves $29.60 automatically (Deficit weight: 120 lbs)!"}
  ], EMERALD);
  addCard(s12, 370, 115, 300, 265, "Engine Implementation & Impact", [
    {label: "Industry Standard", text: "Implements SMC3 CzarLite and Canadian freight deficit rating algorithms."},
    {label: "Simultaneous Evaluation", text: "Evaluates all qualifying weight brackets (MIN, 5C, 1M, 2M, 5M, 10M)."},
    {label: "Audit Trail Notation", text: "Flags calculated quotes with 'is_deficit_rated: True' and records savings."},
    {label: "Broker Edge", text: "Enables brokers to offer lower rates to shippers while protecting margins."},
    {label: "Zero Manual Effort", text: "Eliminates complex deficit calculation cheat-sheets for dispatchers."}
  ], SLATE_DARK);

  // --------------------------------------------------------------------------
  // SLIDE 13: Fuel Surcharge (FSC) Manager
  // --------------------------------------------------------------------------
  var s13 = deck.appendSlide();
  addHeader(s13, "Surcharge Intelligence: Weekly Fuel Surcharge (FSC) Index Manager", "Functional Capabilities", "13/18");
  addCard(s13, 50, 115, 300, 265, "Canadian Diesel Benchmark Integration", [
    {label: "Weekly Dynamic Updates", text: "Tracks fluctuating diesel prices without manual tariff edits."},
    {label: "Ontario Trucking Assn", text: "Pre-seeded with OTA LTL Standard benchmark index (~31.50% FSC)."},
    {label: "Regional Indices", text: "Supports Atlantic Canada LTL benchmarks and Western Canada corridors."},
    {label: "Custom Broker Overrides", text: "Brokers can configure custom fuel percentages (e.g. 35.00%) per account."},
    {label: "Central Benchmark API", text: "Endpoints at /api/fuel-indices/benchmarks manage live fuel tables."}
  ], RED_PRIMARY);
  addCard(s13, 370, 115, 300, 265, "Quoting Engine Integration", [
    {label: "Automated Line-Item", text: "Applies fuel percentage directly to base freight: FSC = Base × (FSC% / 100)."},
    {label: "Full Transparency", text: "Never buries fuel into base freight; itemizes FSC clearly on quote cards."},
    {label: "Multi-Carrier Parity", text: "Applies consistent weekly benchmark rates across all competing options."},
    {label: "Margin Protection", text: "Ensures fuel surcharges adjust automatically as diesel markets shift."},
    {label: "Audit Verification", text: "Records active fuel index code, percentage, and dollar amount in audit logs."}
  ], INDIGO);

  // --------------------------------------------------------------------------
  // SLIDE 14: Rate Sheet Masker & Proposals
  // --------------------------------------------------------------------------
  var s14 = deck.appendSlide();
  addHeader(s14, "Commercial Tools: Rate Sheet Redaction & 1-Click Proposals", "Functional Capabilities", "14/18");
  addCard(s14, 50, 115, 300, 265, "Client-Side Rate Sheet Masker", [
    {label: "Protects Confidentiality", text: "Brokers receive proprietary discounts they cannot share with third parties."},
    {label: "Automated Scrubbing", text: "Scans files and replaces accounts, sales emails, phones, and margin formulas."},
    {label: "100% Rate Preservation", text: "Retains all origin/destination lanes, weight breaks, and rates intact."},
    {label: "Audit Privacy Status", text: "Workbook audit logs confirm 'VERIFIED_SCRUBBED' with total redaction count."},
    {label: "Preview Endpoint", text: "POST /api/ratesift/preview-redaction previews scrubbed files prior to download."}
  ], SLATE_DARK);
  addCard(s14, 370, 115, 300, 265, "1-Click Client Proposal Generator", [
    {label: "Instant Conversion", text: "Converts internal carrier comparison into formal price proposals in 1 click."},
    {label: "Margin Control", text: "Applies markup (+10%, +15%, or target margin) while hiding carrier wholesale costs."},
    {label: "Unique Identifier", text: "Issues formal proposal codes: PROP-YYYYMMDD-XXXXX valid for 7 calendar days."},
    {label: "Printable Web Proposal", text: "Formatted in-browser print layout with professional brokerage letterhead."},
    {label: "Exportable Excel Proposal", text: "Streams styled .xlsx client proposal workbooks ready to email to shippers."}
  ], EMERALD);

  // --------------------------------------------------------------------------
  // SLIDE 15: Market Opportunity & ICP
  // --------------------------------------------------------------------------
  var s15 = deck.appendSlide();
  addHeader(s15, "Business Plan: Market Opportunity & Ideal Customer Profile", "Updated Business Plan", "15/18");
  addCard(s15, 50, 115, 195, 265, "1. Market Size", [
    {label: "$20B+ Market", text: "Over 2,500 licensed freight brokerages and 15,000 dispatchers in Canada."},
    {label: "Excel Reliance", text: "82% of mid-market freight intermediaries price loads using spreadsheets."},
    {label: "Slow Quoting", text: "Average broker takes 18 minutes to quote a multi-carrier LTL load manually."}
  ], RED_PRIMARY);
  addCard(s15, 260, 115, 195, 265, "2. Ideal Customer Profile", [
    {label: "Freight Brokers", text: "Brokerages with 2–20 dispatchers managing 5+ carrier tariff contracts."},
    {label: "Regional 3PLs", text: "Warehousing and logistics hubs offering outsourced shipping services."},
    {label: "Enterprise Shippers", text: "Manufacturers and distributors auditing contracted carrier invoices."},
    {label: "Cross-Border Desks", text: "Forwarders managing freight between Ontario/Quebec and US Midwest."}
  ], INDIGO);
  addCard(s15, 470, 115, 195, 265, "3. Value Proposition", [
    {label: "Pure Quoting", text: "No expensive TMS lock-in; works alongside existing dispatch tools."},
    {label: "2-Min Onboarding", text: "Brokers upload real spreadsheets and start quoting within 2 minutes."},
    {label: "Canadian Residency", text: "Hosted in Canada (WHC), complying with strict PIPEDA privacy standards."},
    {label: "High Daily ROI", text: "Saves 3+ hours per broker daily, paying for itself immediately."}
  ], EMERALD);

  // --------------------------------------------------------------------------
  // SLIDE 16: 4-Tier Pricing Model
  // --------------------------------------------------------------------------
  var s16 = deck.appendSlide();
  addHeader(s16, "Business Plan: Updated 4-Tier Commercial Pricing Model", "Updated Business Plan", "16/18")

  addCard(s16, 50, 115, 140, 265, "Free Starter", [
    {label: "Monthly Price", text: "$0 CAD / month"},
    {label: "Rate Sheets", text: "Up to 3 Sheets"},
    {label: "Monthly Quotes", text: "50 Quotes / mo"},
    {label: "Seats", text: "1 Dispatcher"},
    {label: "Best For", text: "Validating real data without payment"}
  ], SLATE_MUTED);

  addCard(s16, 205, 115, 145, 265, "Broker Pro", [
    {label: "Monthly Price", text: "$79 CAD / month"},
    {label: "Annual (-20%)", text: "$63 / mo ($756/yr)"},
    {label: "Rate Sheets", text: "Up to 10 Sheets"},
    {label: "Monthly Quotes", text: "2,500 Quotes / mo"},
    {label: "Key Features", text: "Canadian fleets, custom markup, history"}
  ], RED_PRIMARY);

  addCard(s16, 365, 115, 145, 265, "Broker Team", [
    {label: "Monthly Price", text: "$199 CAD / month"},
    {label: "Annual (-20%)", text: "$159 / mo ($1,908/yr)"},
    {label: "Rate Sheets", text: "Unlimited Sheets"},
    {label: "Monthly Quotes", text: "15,000 Quotes / mo"},
    {label: "Seats Included", text: "5 Seats (+$25/extra)"}
  ], EMERALD);

  addCard(s16, 525, 115, 145, 265, "Business Custom", [
    {label: "Monthly Price", text: "Custom / Contract"},
    {label: "Quoting Volume", text: "50,000+ API Quotes"},
    {label: "Developer Access", text: "Embedded REST API"},
    {label: "Infrastructure", text: "Dedicated Canadian Cloud"},
    {label: "SLA", text: "99.9% Uptime Guarantee"}
  ], INDIGO);

  // --------------------------------------------------------------------------
  // SLIDE 17: Embedded API & B2B Expansion
  // --------------------------------------------------------------------------
  var s17 = deck.appendSlide();
  addHeader(s17, "B2B Expansion: Embedded Quoting API & Platform Integrations", "Updated Business Plan", "17/18");
  addCard(s17, 50, 115, 300, 265, "Embedded REST API for 3PLs", [
    {label: "Batch Endpoint", text: "POST /api/v1/quotes/batch enables automated rating calls from portals."},
    {label: "Sub-Second SLA", text: "Evaluates multi-carrier rate breaks and minimum floors in under 350ms."},
    {label: "Secure API Keys", text: "Dedicated X-API-Key validation with individual rate limiting."},
    {label: "Interactive Docs", text: "Complete Swagger documentation available at /docs for developers."},
    {label: "Webhook Callbacks", text: "Notifies external ERPs and dispatch systems when calculations complete."}
  ], INDIGO);
  addCard(s17, 370, 115, 300, 265, "High-Value Integration Scenarios", [
    {label: "Shipper Web Portals", text: "3PLs embed RateSift into ordering portals for instant client rates."},
    {label: "Proprietary TMS/ERPs", text: "Connects internal dispatch systems without building rating logic."},
    {label: "E-Commerce Checkout", text: "Wholesalers display accurate freight shipping options at checkout."},
    {label: "Carrier Post-Audit", text: "Shippers audit carrier invoices against original cell coordinates."},
    {label: "Dedicated Cloud Tenant", text: "Enterprise accounts receive isolated database instances in Canada."}
  ], SLATE_DARK);

  // --------------------------------------------------------------------------
  // SLIDE 18: Financial Projections & Roadmap
  // --------------------------------------------------------------------------
  var s18 = deck.appendSlide();
  addHeader(s18, "Financial Outlook: Unit Economics, ARR Projections & Roadmap", "Updated Business Plan", "18/18");
  addCard(s18, 50, 115, 195, 265, "1. Unit Economics", [
    {label: "85%+ Gross Margin", text: "Deterministic algorithms have near-zero compute cost vs LLMs."},
    {label: "Low CAC", text: "Freemium spreadsheet dropzone drives organic broker sign-ups."},
    {label: "Expansion Revenue", text: "Additional seats ($25/seat) and API overage packages."},
    {label: "High Retention", text: "Once carrier tariffs are uploaded, switching costs are high."}
  ], EMERALD);
  addCard(s18, 260, 115, 195, 265, "2. ARR Projections", [
    {label: "Year 1 ARR ($180K)", text: "150 active brokerages (110 Pro, 40 Team) across ON/QC."},
    {label: "Year 2 ARR ($750K)", text: "550 brokerages across Canada + 15 API enterprise contracts."},
    {label: "Year 3 ARR ($2.4M)", text: "1,400 active accounts + US cross-border expansion."},
    {label: "Cash-Flow Positive", text: "Projected profitable by Month 14 of commercial launch."}
  ], RED_PRIMARY);
  addCard(s18, 470, 115, 195, 265, "3. Product Roadmap", [
    {label: "Q1 2027", text: "Live CAD/USD spot exchange rate conversion for cross-border lanes."},
    {label: "Q2 2027", text: "EDI 204/210 Bridge: Automated invoice auditing against quoted cells."},
    {label: "Q3 2027", text: "Rate Anomaly Alerts: Proactive notices when annual renewals spike >20%."},
    {label: "Q4 2027", text: "US Domestic Tariff Corpus: Expand CzarLite across US freight lanes."}
  ], INDIGO);
  s18.getNotesPage().getSpeakerNotesShape().getText().setText("Our financial model is anchored by exceptional unit economics. Because our calculation engine is deterministic Python rather than generative AI, server compute costs are minimal, yielding gross margins above 85%.");

  Logger.log("Created presentation successfully! URL: " + deck.getUrl());
  return deck.getUrl();
}
