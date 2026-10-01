"""
build_presentation.py
=====================
Builds an 18-slide executive Google Slides / PowerPoint presentation for RateSift:
- Complete website page walkthrough (Public & Private Console)
- Deep explanation of functions (Deterministic quoting, FSA resolver, CzarLite deficit rating, FSC manager, redaction, proposal generator)
- Updated business plan summary (4-tier pricing, embedded API, ICP, financial projections)
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

# -----------------------------------------------------------------------------
# BRAND DESIGN TOKENS
# -----------------------------------------------------------------------------
COLOR_RED_PRIMARY = RGBColor(220, 38, 38)     # #DC2626
COLOR_RED_DARK    = RGBColor(153, 27, 27)     # #991B1B
COLOR_RED_LIGHT   = RGBColor(254, 242, 242)   # #FEF2F2
COLOR_SLATE_DARK  = RGBColor(15, 23, 42)      # #0F172A
COLOR_SLATE_NAVY  = RGBColor(30, 41, 59)      # #1E293B
COLOR_SLATE_MUTED = RGBColor(100, 116, 139)   # #64748B
COLOR_SLATE_LIGHT = RGBColor(248, 250, 252)   # #F8FAFC
COLOR_BORDER      = RGBColor(226, 232, 240)   # #E2E8F0
COLOR_WHITE       = RGBColor(255, 255, 255)   # #FFFFFF
COLOR_INDIGO      = RGBColor(79, 70, 229)     # #4F46E5
COLOR_EMERALD     = RGBColor(5, 150, 105)     # #059669
COLOR_AMBER       = RGBColor(217, 119, 6)     # #D97706

LOGO_PATH = os.path.abspath("static/images/ratesift-logo.png")
MOCKUP_PATH = os.path.abspath("static/images/ratesift_console_mockup.jpg")

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
blank_slide_layout = prs.slide_layouts[6]

def apply_background(slide, color=COLOR_WHITE):
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_header(slide, title_text, category_text, slide_num_str):
    """Adds a standard top banner for slides."""
    # Category pill
    pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.4), Inches(2.8), Inches(0.32))
    pill.fill.solid()
    pill.fill.fore_color.rgb = COLOR_RED_LIGHT
    pill.line.color.rgb = RGBColor(254, 202, 202)
    pill.line.width = Pt(1)
    p = pill.text_frame.paragraphs[0]
    p.text = category_text.upper()
    p.font.size = Pt(9.5)
    p.font.bold = True
    p.font.color.rgb = COLOR_RED_PRIMARY
    p.alignment = PP_ALIGN.CENTER

    # Main Title
    title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.75), Inches(9.5), Inches(0.75))
    tf = title_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = title_text
    p.font.size = Pt(22)
    p.font.bold = True
    p.font.color.rgb = COLOR_SLATE_DARK

    # Top right: Logo and slide number
    if os.path.exists(LOGO_PATH):
        try:
            slide.shapes.add_picture(LOGO_PATH, Inches(10.5), Inches(0.42), height=Inches(0.35))
        except Exception:
            pass
            
    num_box = slide.shapes.add_textbox(Inches(12.0), Inches(0.42), Inches(0.6), Inches(0.35))
    tf_num = num_box.text_frame
    p_num = tf_num.paragraphs[0]
    p_num.text = slide_num_str
    p_num.font.size = Pt(11)
    p_num.font.bold = True
    p_num.font.color.rgb = COLOR_SLATE_MUTED
    p_num.alignment = PP_ALIGN.RIGHT

    # Divider line
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.52), Inches(11.733), Inches(0.02))
    line.fill.solid()
    line.fill.fore_color.rgb = COLOR_BORDER
    line.line.fill.background()

def add_card(slide, left, top, width, height, title, bullets, accent_color=COLOR_RED_PRIMARY, bg_color=COLOR_SLATE_LIGHT):
    """Draws a rounded card container with an accent top-bar, title, and bullet list."""
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = bg_color
    card.line.color.rgb = COLOR_BORDER
    card.line.width = Pt(1)

    # Accent line at top of card
    accent = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left + Inches(0.02), top + Inches(0.02), width - Inches(0.04), Inches(0.08))
    accent.fill.solid()
    accent.fill.fore_color.rgb = accent_color
    accent.line.fill.background()

    # Content text
    tb = slide.shapes.add_textbox(left + Inches(0.25), top + Inches(0.2), width - Inches(0.5), height - Inches(0.35))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p_title = tf.paragraphs[0]
    p_title.text = title
    p_title.font.size = Pt(14)
    p_title.font.bold = True
    p_title.font.color.rgb = COLOR_SLATE_DARK
    p_title.space_after = Pt(8)

    for item in bullets:
        p = tf.add_paragraph()
        p.space_after = Pt(5)
        p.font.size = Pt(10.5)
        if isinstance(item, tuple):
            lead, body = item
            run_lead = p.add_run()
            run_lead.text = lead + " "
            run_lead.font.bold = True
            run_lead.font.color.rgb = COLOR_SLATE_DARK

            run_body = p.add_run()
            run_body.text = body
            run_body.font.color.rgb = COLOR_SLATE_MUTED
        else:
            p.text = "• " + item
            p.font.color.rgb = COLOR_SLATE_MUTED

def set_speaker_notes(slide, notes_text):
    notes_slide = slide.notes_slide
    text_frame = notes_slide.notes_text_frame
    text_frame.text = notes_text

# =============================================================================
# SLIDE 1: TITLE SLIDE (Hero Dark Slate)
# =============================================================================
slide1 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide1, COLOR_SLATE_DARK)

# Background subtle card
hero_card = slide1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.0), Inches(1.0), Inches(11.333), Inches(5.5))
hero_card.fill.solid()
hero_card.fill.fore_color.rgb = COLOR_SLATE_NAVY
hero_card.line.color.rgb = RGBColor(51, 65, 85)
hero_card.line.width = Pt(1.5)

# Logo
if os.path.exists(LOGO_PATH):
    try:
        slide1.shapes.add_picture(LOGO_PATH, Inches(1.5), Inches(1.6), height=Inches(0.65))
    except Exception:
        pass

# Badge
badge = slide1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.5), Inches(2.5), Inches(4.5), Inches(0.38))
badge.fill.solid()
badge.fill.fore_color.rgb = RGBColor(69, 10, 10)
badge.line.color.rgb = COLOR_RED_PRIMARY
p = badge.text_frame.paragraphs[0]
p.text = "CANADIAN FREIGHT & LOGISTICS RATING SAAS"
p.font.size = Pt(10)
p.font.bold = True
p.font.color.rgb = RGBColor(254, 202, 202)
p.alignment = PP_ALIGN.CENTER

# Main Title & Subtitle
tb = slide1.shapes.add_textbox(Inches(1.5), Inches(3.1), Inches(10.0), Inches(2.2))
tf = tb.text_frame
tf.word_wrap = True
p1 = tf.paragraphs[0]
p1.text = "RateSift Platform Overview & 2026 Business Plan"
p1.font.size = Pt(32)
p1.font.bold = True
p1.font.color.rgb = COLOR_WHITE
p1.space_after = Pt(10)

p2 = tf.add_paragraph()
p2.text = "Automated Spreadsheet Rating • 100% Deterministic Engine • Strict Zero-Booking Scope"
p2.font.size = Pt(15)
p2.font.color.rgb = RGBColor(203, 213, 225)
p2.space_after = Pt(20)

p3 = tf.add_paragraph()
p3.text = "Prepared for: Executive Leadership & Investors • Hosted in Canada (WHC) • PIPEDA Compliant"
p3.font.size = Pt(11)
p3.font.color.rgb = COLOR_SLATE_MUTED

set_speaker_notes(slide1, 
    "Welcome everyone. Today we are presenting RateSift, an automated freight and shipping rate comparison platform designed specifically for Canadian freight brokers, forwarders, and 3PLs.\n\n"
    "In this presentation, we will walk through all 11 core website views, dive into the functional intelligence powering the engine—including our 100% deterministic rating, Canadian FSA resolver, and deficit rating math—and review the updated 2026 commercial business plan."
)

# =============================================================================
# SLIDE 2: EXECUTIVE SUMMARY & CORE MISSION
# =============================================================================
slide2 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide2)
add_header(slide2, "Executive Summary: The Freight Quoting Bottleneck", "Platform Foundation", "02/18")

add_card(slide2, Inches(0.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "1. The Broker Problem",
    [
        ("Disparate Tariffs:", "Brokers manage dozens of carrier rate cards in differing Excel, CSV, and PDF layouts."),
        ("Manual Cell Hunting:", "Looking up weight breaks, CWT rates, and minimums across sheets takes 15–20 minutes per quote."),
        ("Error-Prone Markups:", "Manual calculations risk underquoting or missing fuel/accessorial surcharges."),
        ("Bloated TMS Solutions:", "Legacy Transportation Management Systems cost $30k–$80k/yr and force operational lock-in.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide2, Inches(4.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "2. The RateSift Solution",
    [
        ("Automated Ingestion:", "Drag-and-drop any carrier Excel spreadsheet; auto-normalizes columns and weight breaks."),
        ("100% Deterministic:", "Every rate is computed via pure Python algorithms—zero LLM guessing or hallucinations."),
        ("Cell-Level Traceability:", "Every quoted rate records its exact origin cell coordinate (e.g. Sheet 1 • Row 14, Col C)."),
        ("1-Click Client Proposals:", "Instantly generates branded customer proposals with broker margins, masking wholesale net rates.")
    ],
    COLOR_EMERALD
)

add_card(slide2, Inches(8.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "3. Strict Scope Boundary",
    [
        ("Quoting Intelligence Only:", "RateSift strictly focuses on rating math, carrier comparison, and client proposals."),
        ("NO Label Printing:", "Zero carrier shipping label generation or thermal printer overhead."),
        ("NO Booking Workflows:", "Does not handle carrier dispatch booking or tender confirmation."),
        ("NO Tracking Numbers:", "Eliminates operational tracking clutter to maintain sub-second computational agility.")
    ],
    COLOR_INDIGO
)

set_speaker_notes(slide2,
    "The core opportunity in freight brokerage is unbundling rating intelligence from bloated legacy TMS software. "
    "Brokers waste hours every day manually cross-referencing multi-tab spreadsheets from carriers like Day & Ross, Manitoulin, Midland, and Bison. "
    "RateSift solves this with zero-baggage quoting: pure calculation and side-by-side comparison. By intentionally refusing to handle labels or tracking, we remain lightning fast, laser-focused, and non-threatening to existing dispatch tools."
)

# =============================================================================
# SLIDE 3: PLATFORM ARCHITECTURE & SITE TOPOLOGY
# =============================================================================
slide3 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide3)
add_header(slide3, "Website Architecture: Public vs. Authenticated Segregation", "Page Architecture", "03/18")

add_card(slide3, Inches(0.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "Public Domain (5 Views)",
    [
        ("Home / Landing ( / ):", "Crawlable SEO hub, value proposition, features overview, FAQ schema, mobile drawer."),
        ("Interactive Demo (/demo):", "Live simulation sandbox preloaded with parcel, pallet, and medical rate sheets."),
        ("Transparent Pricing (/pricing):", "4-tier commercial plans with annual billing toggle (-20%) and capability matrix."),
        ("Log In Screen (/login):", "Distraction-free single card with 1-click test fill for Alex Rivers."),
        ("Get Started Screen (/get-started):", "Frictionless account registration provisioning Free Starter access.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide3, Inches(4.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "Authenticated Console (5 Views)",
    [
        ("Instant Freight Rater (/console/new-quote):", "Broker cockpit with dropzone, Canadian FSA rater, and live multi-carrier ranker."),
        ("Carrier Tariffs (/console/rate-sheets):", "Rate sheet library, cell coordinate inspector, and Human Confirmation Gate."),
        ("Quotes History (/console/history):", "Audit warehouse with RS-YYYYMMDD quote codes, cell references, and Excel export."),
        ("Account Settings (/console/account):", "Broker profile, company branding, default origin hub, and subscription status."),
        ("System Preferences (/console/settings):", "Default markup (+10%), CAD/USD currencies, lb/kg units, and fuel index toggles.")
    ],
    COLOR_EMERALD
)

add_card(slide3, Inches(8.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "Showcase & APIs",
    [
        ("Visual Flowchart (/flowchart):", "Live interactive map showing complete user routing and session transitions."),
        ("Master Showcase (/showcase):", "Multi-viewport device testing toolbar (Mobile 390px, Tablet 768px, Laptop 1024px, Desktop)."),
        ("Embedded Quoting API (/docs):", "Interactive OpenAPI Swagger documentation for programmatic B2B batch quoting."),
        ("Canadian Cloud Tenancy:", "All sessions, tariffs, and database queries are hosted in Canada (WHC / PIPEDA).")
    ],
    COLOR_INDIGO
)

set_speaker_notes(slide3,
    "The RateSift platform is architected into three clear zones: the crawlable Public Domain for organic search acquisition, the Authenticated Console where brokers perform their daily rating workflows, and the Developer Showcase and API layer. "
    "Every route is guarded with session cookies. If an unauthenticated user attempts to visit the console, they are smoothly redirected to login with their intended destination preserved."
)

# =============================================================================
# SLIDE 4: PUBLIC PAGES — HOME & INTERACTIVE DEMO
# =============================================================================
slide4 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide4)
add_header(slide4, "Public Experience: High-Converting SEO & Interactive Demo", "Website Walkthrough", "04/18")

add_card(slide4, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "Home / Landing Page ( GET / )",
    [
        ("Semantic SEO & Breadcrumbs:", "Optimized for terms like 'Canadian freight rater', 'batch Excel shipping calculator', and '3PL rate engine'."),
        ("Responsive Layout:", "Fluid container scaling from 390px mobile screens up to 1400px ultra-wide monitors."),
        ("Mobile Hamburger Drawer:", "Collapsible navigation drawer ensuring seamless browsing on smartphones."),
        ("Structured Data Schema:", "SoftwareApplication, AggregateOffer, and FAQPage JSON-LD schemas embedded for Google rich snippets."),
        ("Clear Call-to-Actions:", "Direct pathways to test the live Demo sandbox or register for the Free Starter tier.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide4, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "Interactive Demo Sandbox ( GET /demo )",
    [
        ("Zero-Registration Testing:", "Prospective clients can evaluate calculation speed and accuracy without creating an account."),
        ("Preloaded Canadian Tariffs:", "Includes sample carrier sheets for Parcels, General LTL Pallets, and Medical/Cold Cargo."),
        ("Real-Time Sliders:", "Interactive sliders for weight (100–10,000 lbs) and toggles for tailgate, appointment, and heated service."),
        ("Side-by-Side Carrier Output:", "Renders instant price rankings comparing Day & Ross, Manitoulin, Midland, and Bison."),
        ("Transparent Cell Coordinate Inspection:", "Highlights the exact row and column coordinate from which every rate was extracted.")
    ],
    COLOR_INDIGO
)

set_speaker_notes(slide4,
    "The public pages are designed to turn skeptical logistics managers into active users within 60 seconds. "
    "The landing page establishes our unique value proposition: pure quoting, zero label bloat, Canadian data sovereignty. "
    "The Demo page lets visitors immediately interact with live calculations. When they see rates calculate dynamically across weight breaks and accessorials, trust is instantly built."
)

# =============================================================================
# SLIDE 5: PUBLIC PAGES — PRICING & DISTRACTION-FREE AUTH
# =============================================================================
slide5 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide5)
add_header(slide5, "Public Pages: Transparent Pricing & Distraction-Free Auth", "Website Walkthrough", "05/18")

add_card(slide5, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "Transparent Pricing Page ( GET /pricing )",
    [
        ("4 Clear Commercial Tiers:", "Free Starter ($0), Broker Pro ($79 CAD/mo), Broker Team ($199 CAD/mo), and Business Custom."),
        ("Annual Billing Discount Switch:", "Interactive toggle calculates instant 20% annual discount across all paid plans."),
        ("Detailed Capability Matrix:", "Uncompromising comparison table detailing active rate sheets, monthly quote quotas, and API access."),
        ("Embedded Quoting API Spotlight:", "Outlines REST endpoints and sub-second SLAs for 3PLs integrating rate lookups into customer portals."),
        ("Zero-Bloat Guarantee:", "Reinforces that customers never pay for unnecessary label or dispatch features.")
    ],
    COLOR_EMERALD
)

add_card(slide5, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "Auth Screens ( GET /login & /get-started )",
    [
        ("Single Centered Card Design:", "Distraction-free authentication form centered vertically and horizontally on all viewports."),
        ("1-Click Demo Auto-Fill:", "Instant auto-fill button for Alex Rivers (Broker Specialist) enables seamless 1-click evaluation."),
        ("Secure 30-Day Sessions:", "Issues HTTP-only, secure session cookies (ratesift_session) for authenticated console access."),
        ("Frictionless Onboarding:", "New registrations automatically provision Free Starter access (3 sheets / 50 monthly quotes)."),
        ("Smart Post-Login Routing:", "Respects the 'next' URL parameter to return users to their exact workflow after logging in.")
    ],
    COLOR_SLATE_DARK
)

set_speaker_notes(slide5,
    "Our pricing page is completely transparent—no hidden setup fees or opaque sales gates. We offer an interactive monthly/annual switch that saves 20% on yearly plans. "
    "On authentication, we adhere to a strict design rule: a clean, single centered card without sidebar clutter. The 1-click test fill allows stakeholders and evaluators to experience the platform instantly as demo broker Alex Rivers."
)

# =============================================================================
# SLIDE 6: CONSOLE — INSTANT FREIGHT RATER COCKPIT
# =============================================================================
slide6 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide6)
add_header(slide6, "Console: Instant Freight Rater Cockpit ( /console/new-quote )", "Console Walkthrough", "06/18")

# Left Column: Features
add_card(slide6, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "The Broker's Quoting Center",
    [
        ("Canadian FSA Origin/Destination:", "Type any Canadian postal code (e.g. M5V 2T6) or city; resolves to normalized freight hubs."),
        ("Shipment Weight & Dimensions:", "Handles actual vs. dimensional weight calculations with standard cubic divisors."),
        ("Comprehensive Accessorials:", "Checkboxes for Tailgate/Liftgate, Delivery Appointment, Residential, and Heated Service."),
        ("Multi-Carrier Ranking Cards:", "Ranked side-by-side with carrier name, transit days, base rate, fuel surcharge, and final total."),
        ("Client-Side In-Memory Re-Sorting:", "Instant 1-click buttons: 'Lowest Price', 'Fastest Transit', and 'Best Value' without API delays."),
        ("Deep Line-Item Audit Accordion:", "1-click expansion reveals hundredweight tier, minimum floor adjustments, and source cells.")
    ],
    COLOR_RED_PRIMARY
)

# Right Column: Platform Screenshot/Mockup
if os.path.exists(MOCKUP_PATH):
    try:
        slide6.shapes.add_picture(MOCKUP_PATH, Inches(6.8), Inches(1.8), width=Inches(5.7))
    except Exception:
        pass

# Caption box below picture
caption = slide6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.8), Inches(5.3), Inches(5.7), Inches(1.5))
caption.fill.solid()
caption.fill.fore_color.rgb = COLOR_SLATE_LIGHT
caption.line.color.rgb = COLOR_BORDER
tf_c = caption.text_frame
tf_c.word_wrap = True
p = tf_c.paragraphs[0]
p.text = "Key UI Innovation: In-Memory Sorting & Coordinate Audit"
p.font.size = Pt(12)
p.font.bold = True
p.font.color.rgb = COLOR_SLATE_DARK
p.space_after = Pt(4)
p2 = tf_c.add_paragraph()
p2.text = "Brokers can compare Day & Ross, Manitoulin, Midland, and Bison in real-time, re-sort by speed or price in 0ms, and verify every rate against original spreadsheet cells."
p2.font.size = Pt(10)
p2.font.color.rgb = COLOR_SLATE_MUTED

set_speaker_notes(slide6,
    "This is the heart of RateSift: the Instant Freight Rater console. "
    "Brokers enter origin and destination postal codes, input weight and accessorials, and instantly receive ranked quotes from all confirmed carriers. "
    "Notice the in-memory re-sorting: brokers can switch between lowest price, fastest transit, and best value instantaneously on the client side without triggering slow server round-trips."
)

# =============================================================================
# SLIDE 7: CONSOLE — EXCEL INGESTION & DOCUMENT CLASSIFIER
# =============================================================================
slide7 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide7)
add_header(slide7, "Console: Excel Ingestion & 7-Category Document Classifier", "Console Walkthrough", "07/18")

add_card(slide7, Inches(0.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "1. Autonomous Dropzone",
    [
        ("Multi-Format Ingestion:", "Accepts .xlsx, .xls, and .csv rate cards from any major Canadian or US carrier."),
        ("Header Detection:", "Scans rows dynamically to detect rate break matrices at arbitrary spreadsheet positions."),
        ("Currency & Unit Capture:", "Explicitly records CAD vs USD, lbs vs kg, and inches vs cm without guessing.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide7, Inches(4.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "2. 7-Category Classification",
    [
        ("Rate Matrix Rows:", "Ingested into normalized rate break tables for mathematical rating."),
        ("Letterhead Exclusion (Rule 34):", "Automatically quarantines carrier contact info and billing addresses."),
        ("Disclaimer Quarantine (Rule 35):", "Isolates legal terms and E&OE boilerplate from numeric rating math."),
        ("Prose Accessorials (Rule 36):", "Extracts surcharges embedded in descriptive text into structured fee ledgers.")
    ],
    COLOR_INDIGO
)

add_card(slide7, Inches(8.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "3. Human Confirmation Gate",
    [
        ("Rule 7 & 19 Enforcement:", "Newly uploaded sheets remain PENDING_REVIEW until confirmed by a human broker."),
        ("Confusion Gate Detection:", "When header candidates score within 10% confidence, system halts and requests user verification."),
        ("Rich Ingestion Preview:", "Displays sample headers, candidate row numbers, and underlying data rows for 1-click confirmation.")
    ],
    COLOR_EMERALD
)

set_speaker_notes(slide7,
    "Carrier rate sheets are notoriously messy—often containing company letterheads, nested footnotes, and legal disclaimers. "
    "Our Autonomous Document Classifier classifies every row into seven distinct categories. It quarantines letterheads and legal disclaimers so they never corrupt calculation matrices. "
    "Most importantly, Rules 7 and 19 enforce our Human Confirmation Gate: a sheet cannot be used for live quoting until a human verifies the extraction."
)

# =============================================================================
# SLIDE 8: CONSOLE — CARRIER TARIFFS & CELL COORDINATES
# =============================================================================
slide8 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide8)
add_header(slide8, "Console: Carrier Tariffs & Source Cell Coordinates", "Console Walkthrough", "08/18")

add_card(slide8, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "Carrier Tariffs Library ( /console/rate-sheets )",
    [
        ("Central Tariff Repository:", "Manage active, pending, and archived rate cards across all contracted carriers."),
        ("Version Precedence (Rule 17):", "Automatically detects multiple tariff revisions; uses the latest valid version and flags older revisions as superseded."),
        ("Effective & Expiry Filtering (Rule 16):", "Excludes expired tariffs or future-dated rate sheets with clear broker alerts."),
        ("Tariff Status Badges:", "Visual indicators displaying CONFIRMED (ready for rating), PENDING_REVIEW, or ARCHIVED."),
        ("One-Click Re-Extraction:", "Brokers can trigger re-parsing or review extracted accessorial rules at any time.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide8, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "Source Traceability & Cell Coordinates (Rule 3)",
    [
        ("Zero Black-Box Pricing:", "Every extracted rate records its exact origin cell coordinate in the database."),
        ("Cell Coordinate Notation:", "Expressed as 'Sheet 1 • Row 14, Col C' or '[Tariff-2026] Rates!D12'."),
        ("Audit Defense for Brokers:", "When a customer or accounting department questions a freight quote, brokers can pinpoint the exact cell in seconds."),
        ("Cell Coordinate Inspector Modal:", "Clicking any rate card allows brokers to inspect all underlying cell coordinates in an interactive table."),
        ("Canadian Data Residency Tag:", "Every cell record is tagged with 'CA_CENTRAL_WHC' ensuring strict PIPEDA compliance.")
    ],
    COLOR_INDIGO
)

set_speaker_notes(slide8,
    "Rule 3 is a major competitive differentiator for RateSift: complete Source Traceability. "
    "Every single number—base rates, CWT breaks, accessorial percentages—tracks its exact source coordinate back to the original spreadsheet. "
    "In freight brokerage, disputes over billed charges are common. With RateSift, a broker can defend any quote instantly by citing the exact spreadsheet row and column."
)

# =============================================================================
# SLIDE 9: CONSOLE — QUOTES HISTORY & PREFERENCES
# =============================================================================
slide9 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide9)
add_header(slide9, "Console: Quotes History Warehouse & System Preferences", "Console Walkthrough", "09/18")

add_card(slide9, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "Quotes History Warehouse ( /console/history )",
    [
        ("Immutable Audit Trail (Rule 30):", "Every calculation generates a unique, permanent audit ID (e.g. RS-20261001-A9F3)."),
        ("Real-Time Search & Filtering:", "Instant client-side search by Quote ID, carrier name, origin city, or destination postal code."),
        ("Sort by Rate:", "Interactive dropdown to sort archived quotes by total rate (High-to-Low or Low-to-High)."),
        ("Coordinate Retention:", "Historical records retain cell references and applied accessorial details indefinitely."),
        ("Excel Workbook Export:", "1-click 'Export to Excel' streams formatted .xlsx spreadsheets for accounting or client reporting.")
    ],
    COLOR_EMERALD
)

add_card(slide9, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "Account & Preferences ( /console/settings )",
    [
        ("Dynamic Broker Markup:", "Set default margin markups (e.g. +10% or +15%) applied dynamically to base carrier freight."),
        ("Currency & Units Standards:", "Toggle between CAD and USD, and switch weight units between pounds (lbs) and kilograms (kg)."),
        ("Origin Dispatch Presets:", "Configure default dispatch hubs (e.g. Toronto M5V 2T6 or Montreal H3B 1A1) for accelerated entry."),
        ("Fuel Index Integration:", "Select default diesel benchmark indices (OTA Standard, Atlantic, Western, or Custom broker percentage)."),
        ("Brokerage Branding:", "Customize broker company name and dispatcher email shown on generated client proposals.")
    ],
    COLOR_SLATE_DARK
)

set_speaker_notes(slide9,
    "The Quotes History Warehouse provides an immutable audit trail. "
    "Every quote calculation is archived with an RS-formatted identifier, timestamps, input parameters, and exact cell coordinates. "
    "Under System Preferences, brokers can configure default markups, preferred diesel indices, and dispatch hubs so that rating calculations reflect their exact commercial strategy."
)

# =============================================================================
# SLIDE 10: FUNCTION DEEP DIVE — 100% DETERMINISTIC QUOTING
# =============================================================================
slide10 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide10)
add_header(slide10, "Rating Intelligence: 100% Deterministic Engine (Zero AI Hallucinations)", "Functional Capabilities", "10/18")

add_card(slide10, Inches(0.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "1. Pure Mathematical Math",
    [
        ("Rule 8 Compliance:", "Pricing is calculated strictly by deterministic Python algorithms—never generative LLM guesses."),
        ("Rule 14 Idempotency:", "Identical inputs against the same carrier tariff will always yield the exact same penny-perfect total."),
        ("Final-Step Rounding (Rule 15):", "All intermediate fractions are preserved; final half-up rounding to 2 decimals occurs at the final step.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide10, Inches(4.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "2. CWT & Minimum Floors",
    [
        ("Hundredweight Scaling:", "Calculates base freight: (Weight / 100) × CWT Rate across brackets (LTL, 5C, 1M, 2M, 5M, 10M)."),
        ("Rule 12 Minimum Floors:", "Compares calculated base charge against carrier's lane minimum floor and bills the higher amount."),
        ("Audit Transparency:", "When a minimum floor is applied, the audit log clearly flags 'min_charge_adjustment'.")
    ],
    COLOR_INDIGO
)

add_card(slide10, Inches(8.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "3. Dimensional Weight (DIM)",
    [
        ("Rule 9 Divisor Math:", "Evaluates cubic dimensions using carrier divisors: (L × W × H) / 139 (or 166 / 250)."),
        ("PCF Density Rules:", "Supports Pounds Per Cubic Foot (PCF) density rating for high-cube, low-density cargo."),
        ("Bill on Greater:", "Engine compares actual scale weight vs. dimensional weight and bills on whichever is greater.")
    ],
    COLOR_EMERALD
)

set_speaker_notes(slide10,
    "A foundational design principle of RateSift is Rule 8: 100% Deterministic Pricing. "
    "In freight logistics, quoting an incorrect number by even a few dollars can destroy broker margins or lose key accounts. We never use language models to calculate rates. "
    "Our engine enforces hundredweight scaling, carrier minimum floors, and dimensional weight rules mathematically with zero hallucinations."
)

# =============================================================================
# SLIDE 11: FUNCTION DEEP DIVE — CANADIAN POSTAL FSA RESOLVER
# =============================================================================
slide11 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide11)
add_header(slide11, "Geographic Intelligence: Canadian Postal FSA Resolver", "Functional Capabilities", "11/18")

add_card(slide11, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "1,600+ Canadian Postal FSAs Mapped",
    [
        ("Forward Sortation Area (FSA):", "Resolves first 3 characters of any Canadian postal code to official carrier terminal zones."),
        ("Downtown Hubs:", "M5V 2T6 resolves to TORONTO, ON (Zone: ON-TOR) • H3B 1A1 resolves to MONTREAL, QC (Zone: QC-MTL)."),
        ("Western Hubs:", "T2P 1J9 resolves to CALGARY, AB (Zone: AB-CAL) • V6B 2W9 resolves to VANCOUVER, BC (Zone: BC-VAN)."),
        ("Dorval West Island Cargo Hub:", "H9P 1K2 resolves to Dorval cargo terminal with regional drayage rules."),
        ("Rural Territory Detection:", "Flags remote or rural postal codes (e.g. secondary digit '0') for carrier beyond-charge surcharges.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide11, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "Lane Corridors & Carrier Zone Normalization",
    [
        ("Freight Corridor Mapping:", "Automatically classifies inter-provincial lanes into standard corridors (ON-QC, ON-AB, BC-AB)."),
        ("Carrier-Specific Zones (Rule 10):", "Maps origin/destination into each individual carrier's proprietary zone scheme, not generic estimates."),
        ("Dedicated REST APIs:", "Exposes GET /api/geo/resolve-fsa and GET /api/geo/resolve-lane for third-party developer integration."),
        ("Sub-Millisecond Lookup:", "In-memory indexed database delivers location resolution in under 2 milliseconds."),
        ("Error Prevention (Rule 25):", "Rejects unresolvable postal codes with clear HTTP 400 validation prompts.")
    ],
    COLOR_INDIGO
)

set_speaker_notes(slide11,
    "Canadian freight rating depends entirely on Postal Code FSAs—the first three characters of the postal code. "
    "RateSift incorporates a comprehensive database of over 1,600 Canadian FSAs. "
    "When a broker enters 'M5V 2T6', the system instantly resolves it to Toronto, maps the carrier's proprietary zone, identifies the corridor, and applies any rural territory accessorials automatically."
)

# =============================================================================
# SLIDE 12: FUNCTION DEEP DIVE — SMC3 CZARLITE & DEFICIT RATING
# =============================================================================
slide12 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide12)
add_header(slide12, "Pricing Optimization: SMC3 CzarLite & Deficit Weight Rating", "Functional Capabilities", "12/18")

add_card(slide12, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "The Deficit Rating Principle",
    [
        ("The Freight Anomaly:", "In standard CWT tier pricing, shipments near weight break thresholds can cost more than heavier shipments."),
        ("Automated Deficit Bumping:", "The engine automatically tests whether bumping shipment weight to the minimum of the next bracket yields a lower price."),
        ("Real-World Math Example:", "A shipment weighs 880 lbs on Toronto → Montreal:"),
        ("• Natural Tier (5C @ $42.00/CWT):", "(880 / 100) × $42.00 = $369.60 base charge."),
        ("• Deficit Bumped (1M @ $34.00/CWT):", "(1,000 / 100) × $34.00 = $340.00 base charge."),
        ("Instant Broker Savings:", "Direct client savings of $29.60 (Deficit weight: 120 lbs) applied automatically!")
    ],
    COLOR_EMERALD
)

add_card(slide12, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "Engine Implementation & Transparency",
    [
        ("Industry Standard Compliance:", "Implements SMC3 CzarLite and Canadian freight rating deficit rules."),
        ("Multi-Tier Evaluation:", "Evaluates all qualifying weight brackets (MIN, 5C, 1M, 2M, 5M, 10M) simultaneously."),
        ("Audit Trail Annotation:", "Flags calculated quotes with 'is_deficit_rated: True' and records exact dollar savings achieved."),
        ("Broker Competitive Advantage:", "Enables brokers to offer lower rates to shippers while protecting healthy margins."),
        ("Zero Manual Calculations:", "Eliminates the need for dispatchers to maintain complex deficit calculation cheat-sheets.")
    ],
    COLOR_SLATE_DARK
)

set_speaker_notes(slide12,
    "Deficit weight rating is an essential technique used by top freight brokers. "
    "When a shipment is near a weight break—such as 880 lbs—bumping the billed weight to the 1,000 lb threshold drops the rate per hundredweight enough to produce a cheaper total price. "
    "RateSift calculates this automatically across every carrier and weight break, saving shippers money and giving brokers an immediate competitive edge."
)

# =============================================================================
# SLIDE 13: FUNCTION DEEP DIVE — FUEL SURCHARGE (FSC) MANAGER
# =============================================================================
slide13 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide13)
add_header(slide13, "Surcharge Intelligence: Weekly Fuel Surcharge (FSC) Index Manager", "Functional Capabilities", "13/18")

add_card(slide13, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "Canadian Diesel Benchmark Integration",
    [
        ("Dynamic Weekly FSC Updates:", "Tracks fluctuating diesel prices without requiring manual edits to underlying carrier tariffs."),
        ("Ontario Trucking Association (OTA):", "Pre-seeded with OTA LTL Standard benchmark index (~31.50% FSC)."),
        ("Regional Canadian Indices:", "Supports Atlantic Canada LTL benchmarks and Western Canada corridors."),
        ("Custom Broker Overrides:", "Brokers can configure a custom fuel surcharge percentage (e.g. 35.00%) per tenant."),
        ("Central Benchmark API:", "Endpoints at /api/fuel-indices/benchmarks and /api/fuel-indices/settings manage live fuel tables.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide13, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "Seamless Quoting Engine Integration",
    [
        ("Automated Line-Item Surcharge:", "Applies effective fuel percentage directly to base freight: FSC = Base × (FSC% / 100)."),
        ("Full Transparency (Rule 13):", "Never buries fuel into base freight; itemizes FSC clearly on quote cards and client proposals."),
        ("Multi-Carrier Parity:", "Applies consistent weekly benchmark rates across all competing carrier options for fair comparison."),
        ("Broker Margin Protection:", "Ensures fuel surcharges adjust automatically as diesel markets shift week to week."),
        ("Audit Log Verification:", "Records active fuel index code, percentage, and dollar amount in quote audit logs.")
    ],
    COLOR_INDIGO
)

set_speaker_notes(slide13,
    "Fuel surcharges represent 25% to 35% of total freight costs in Canada. "
    "Because diesel prices change weekly, hardcoding fuel into static spreadsheets is a recipe for margin erosion. "
    "RateSift integrates weekly diesel benchmarks from the Ontario Trucking Association and regional freight councils. "
    "Brokers can update fuel once in System Preferences, and the engine immediately recalculates fuel across every carrier quote."
)

# =============================================================================
# SLIDE 14: FUNCTION DEEP DIVE — REDACTION & PROPOSAL GENERATOR
# =============================================================================
slide14 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide14)
add_header(slide14, "Commercial Tools: Rate Sheet Redaction & 1-Click Proposals", "Functional Capabilities", "14/18")

add_card(slide14, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "Client-Side Rate Sheet Masker / Redactor",
    [
        ("Protects Confidential Data:", "Freight brokers frequently receive proprietary discounts they cannot share publicly."),
        ("Automated Data Scrubbing:", "Scans workbooks and replaces account numbers, sales emails, phone numbers, and margin targets with redaction tags."),
        ("100% Rate Preservation:", "Retains all origin/destination lanes, weight breaks, and numeric rates intact."),
        ("Audit Privacy Status:", "Workbook audit logs confirm 'VERIFIED_SCRUBBED' with total redaction count."),
        ("REST Endpoint:", "POST /api/ratesift/preview-redaction previews scrubbed files before downloading.")
    ],
    COLOR_SLATE_DARK
)

add_card(slide14, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "1-Click Client Proposal Generator",
    [
        ("Instant Client Conversion:", "Converts internal carrier comparison into client-facing formal price proposals in 1 click."),
        ("Margin & Markup Control:", "Applies broker markup (+10%, +15%, or custom total) while completely hiding carrier wholesale costs."),
        ("Unique Proposal Identifier:", "Issues formal proposal codes: PROP-YYYYMMDD-XXXXX valid for 7 calendar days."),
        ("Printable Web Proposal:", "Formatted in-browser print layout with clean page breaks and professional brokerage letterhead."),
        ("Exportable Excel Proposal:", "Streams styled .xlsx client proposal workbooks ready to email to shippers.")
    ],
    COLOR_EMERALD
)

set_speaker_notes(slide14,
    "These two commercial tools complete the broker's daily workflow. "
    "The Rate Sheet Masker protects broker confidentiality by scrubbing carrier account numbers, sales rep emails, and target margins before sharing rate sheets. "
    "The 1-Click Client Proposal Generator turns winning carrier rates into professional client quotes in seconds. "
    "Brokers set their target margin, and RateSift produces a branded proposal hiding wholesale carrier net costs."
)

# =============================================================================
# SLIDE 15: BUSINESS PLAN — MARKET OPPORTUNITY & ICP
# =============================================================================
slide15 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide15)
add_header(slide15, "Business Plan: Market Opportunity & Ideal Customer Profile", "Updated Business Plan", "15/18")

add_card(slide15, Inches(0.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "1. Market Size & Demand",
    [
        ("$20B+ Canadian Freight Market:", "Over 2,500 licensed freight brokerages and 15,000 independent dispatchers operating in Canada."),
        ("High Spreadsheet Reliance:", "82% of mid-market freight intermediaries still calculate quotes using Microsoft Excel."),
        ("Inefficient Quoting Cycles:", "Average broker takes 18 minutes to price a multi-carrier LTL load manually.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide15, Inches(4.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "2. Ideal Customer Profile (ICP)",
    [
        ("Mid-Market Freight Brokers:", "Brokerages with 2–20 dispatchers managing 5+ carrier tariff contracts."),
        ("Regional 3PL Providers:", "Warehousing and logistics hubs offering outsourced shipping services to Canadian shippers."),
        ("Enterprise Shipping Desks:", "High-volume manufacturers and distributors wanting to audit contracted carrier bills."),
        ("Cross-Border Forwarders:", "Forwarders managing freight lanes between Ontario/Quebec and US Midwest/Northeast.")
    ],
    COLOR_INDIGO
)

add_card(slide15, Inches(8.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "3. Unique Value Proposition",
    [
        ("Pure Quoting Focus:", "No expensive TMS lock-in; works alongside existing dispatch tools."),
        ("Fast Time-to-Value:", "Brokers upload their real spreadsheets and start quoting within 2 minutes."),
        ("Canadian Sovereignty:", "All data resident in Canada, complying with WHC hosting standards and PIPEDA privacy laws."),
        ("High ROI:", "Saves 3+ hours per broker daily, paying for itself on day one.")
    ],
    COLOR_EMERALD
)

set_speaker_notes(slide15,
    "Let's look at the commercial opportunity. The Canadian freight market is over $20 billion, with thousands of freight brokerages still relying on manual spreadsheets. "
    "Our Ideal Customer Profile is the mid-market freight broker and regional 3PL. "
    "They do not want another complex, $50,000 TMS that takes six months to implement. They want a fast, focused tool that ingests their rate sheets and returns ranked quotes in seconds."
)

# =============================================================================
# SLIDE 16: BUSINESS PLAN — 4-TIER COMMERCIAL PRICING
# =============================================================================
slide16 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide16)
add_header(slide16, "Business Plan: Updated 4-Tier Commercial Pricing Model", "Updated Business Plan", "16/18")

# Table for Pricing
table_shape = slide16.shapes.add_table(5, 5, Inches(0.8), Inches(1.8), Inches(11.733), Inches(5.0))
table = table_shape.table

# Column widths
table.columns[0].width = Inches(2.933)
table.columns[1].width = Inches(2.2)
table.columns[2].width = Inches(2.2)
table.columns[3].width = Inches(2.2)
table.columns[4].width = Inches(2.2)

headers = ["Plan Metric", "Free Starter", "Broker Pro", "Broker Team", "Business Custom"]
for col_idx, h in enumerate(headers):
    cell = table.cell(0, col_idx)
    cell.fill.solid()
    cell.fill.fore_color.rgb = COLOR_SLATE_DARK if col_idx != 2 else COLOR_RED_PRIMARY
    p = cell.text_frame.paragraphs[0]
    p.text = h
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = COLOR_WHITE
    p.alignment = PP_ALIGN.CENTER if col_idx > 0 else PP_ALIGN.LEFT

row_data = [
    ("Monthly Pricing (CAD)", "$0 / month", "$79 / month", "$199 / month", "Custom / Contract"),
    ("Annual Pricing (-20%)", "Free Forever", "$63 / mo ($756/yr)", "$159 / mo ($1,908/yr)", "Annual SLA Contract"),
    ("Active Rate Sheets", "Up to 3 Sheets", "Up to 10 Sheets", "Unlimited Sheets", "Unlimited Sheets"),
    ("Monthly Batch Quotes", "50 Quotes / mo", "2,500 Quotes / mo", "15,000 Quotes / mo", "50,000+ API Quotes"),
]

for row_idx, r in enumerate(row_data):
    for col_idx, val in enumerate(r):
        cell = table.cell(row_idx + 1, col_idx)
        cell.fill.solid()
        if col_idx == 2:
            cell.fill.fore_color.rgb = COLOR_RED_LIGHT
        elif row_idx % 2 == 1:
            cell.fill.fore_color.rgb = COLOR_SLATE_LIGHT
        else:
            cell.fill.fore_color.rgb = COLOR_WHITE
            
        p = cell.text_frame.paragraphs[0]
        p.text = val
        p.font.size = Pt(10.5)
        p.font.bold = (col_idx == 0 or row_idx == 0)
        p.font.color.rgb = COLOR_SLATE_DARK if col_idx != 2 or row_idx != 0 else COLOR_RED_PRIMARY
        p.alignment = PP_ALIGN.CENTER if col_idx > 0 else PP_ALIGN.LEFT

set_speaker_notes(slide16,
    "Our monetization strategy is designed for land-and-expand. "
    "Free Starter lets any broker upload up to 3 real rate sheets and process 50 quotes per month with no credit card required. "
    "Broker Pro at $79 CAD/month targets solo brokers and small teams. "
    "Broker Team at $199 CAD/month includes 5 dispatcher seats and 15,000 quotes, with additional seats at $25/month. "
    "Business Custom provides high-volume API access for 3PLs and enterprise shippers."
)

# =============================================================================
# SLIDE 17: BUSINESS PLAN — EMBEDDED QUOTING API & EXPANSION
# =============================================================================
slide17 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide17)
add_header(slide17, "B2B Expansion: Embedded Quoting API & Platform Integrations", "Updated Business Plan", "17/18")

add_card(slide17, Inches(0.8), Inches(1.8), Inches(5.6), Inches(5.0),
    "Embedded REST API for 3PLs & Platforms",
    [
        ("Programmatic Batch Quoting:", "POST /api/v1/quotes/batch enables automated rating calls directly from customer portals."),
        ("Sub-Second Latency SLA:", "Engine evaluates multi-carrier rate breaks and minimum floors in under 350ms."),
        ("Secure API Key Authentication:", "Dedicated X-API-Key validation with individual rate limiting and usage metering."),
        ("Interactive OpenAPI Documentation:", "Complete Swagger docs available at /docs for seamless developer onboarding."),
        ("Webhook Event Callbacks:", "Notifies external ERPs and dispatch systems when batch calculations complete.")
    ],
    COLOR_INDIGO
)

add_card(slide17, Inches(6.8), Inches(1.8), Inches(5.7), Inches(5.0),
    "High-Value B2B Integration Scenarios",
    [
        ("Customer-Facing Shipper Portals:", "3PLs embed RateSift into their client ordering portals, giving shippers instant rate estimates."),
        ("Proprietary Brokerage TMS & ERPs:", "Brokers connect internal dispatch systems to RateSift without building rating logic in-house."),
        ("E-Commerce & B2B Checkout:", "Wholesalers display accurate freight shipping options at online checkout for heavy freight."),
        ("Carrier Audit & Reconciliation:", "Shippers run post-billing freight audits against stored cell coordinates to catch billing errors."),
        ("Dedicated Canadian Cloud Tenant:", "Enterprise tier includes isolated database instances hosted in Montreal or Toronto.")
    ],
    COLOR_SLATE_DARK
)

set_speaker_notes(slide17,
    "Our longer-term expansion strategy centers on the Embedded Quoting API. "
    "Instead of 3PLs building their own complex rating engines from scratch, they call RateSift via REST API with an API key. "
    "With sub-second latency and guaranteed Canadian data residency, RateSift becomes the quoting infrastructure behind third-party freight portals, ERPs, and e-commerce checkouts."
)

# =============================================================================
# SLIDE 18: BUSINESS PLAN — FINANCIAL PROJECTIONS & ROADMAP
# =============================================================================
slide18 = prs.slides.add_slide(blank_slide_layout)
apply_background(slide18)
add_header(slide18, "Financial Outlook: Unit Economics, ARR Projections & Roadmap", "Updated Business Plan", "18/18")

add_card(slide18, Inches(0.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "1. Unit Economics",
    [
        ("85%+ Gross Software Margin:", "Deterministic Python algorithms have near-zero compute cost compared to GPU-heavy LLMs."),
        ("Low Acquisition Cost (CAC):", "Freemium spreadsheet dropzone drives organic broker sign-ups and viral word-of-mouth."),
        ("Expansion Revenue:", "Expansion via additional dispatcher seats ($25/seat) and high-volume API overage packages."),
        ("High Broker Retention:", "Once carrier tariffs are uploaded and verified, switching costs are high.")
    ],
    COLOR_EMERALD
)

add_card(slide18, Inches(4.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "2. 3-Year ARR Projections",
    [
        ("Year 1 ARR ($180K CAD):", "150 active brokerage accounts (110 Pro, 40 Team) across Ontario and Quebec."),
        ("Year 2 ARR ($750K CAD):", "550 brokerages across Canada + 15 3PL Embedded API enterprise contracts."),
        ("Year 3 ARR ($2.4M CAD):", "1,400 active accounts + national carrier partnerships and cross-border US expansion."),
        ("Path to Profitability:", "Cash-flow positive projected by Month 14 of commercial launch.")
    ],
    COLOR_RED_PRIMARY
)

add_card(slide18, Inches(8.8), Inches(1.8), Inches(3.7), Inches(5.0),
    "3. Product Roadmap",
    [
        ("Q1 2027: Multi-Currency:", "Live CAD/USD spot exchange rate conversion for cross-border US-Canada lanes."),
        ("Q2 2027: EDI 204/210 Bridge:", "Automated invoice comparison against original quoted spreadsheet cells."),
        ("Q3 2027: Rate Anomaly Alerts:", "Proactive alerts when carrier annual tariff renewals increase lane costs by >20%."),
        ("Q4 2027: US Domestic Tariff Corpus:", "Expand CzarLite corpus across US South and West freight lanes.")
    ],
    COLOR_INDIGO
)

set_speaker_notes(slide18,
    "To conclude, our financial model is anchored by exceptional unit economics. Because our calculation engine is deterministic Python rather than generative AI, our server compute costs are minimal, yielding gross margins above 85%. "
    "We project reaching $180,000 CAD ARR in Year 1, scaling to $750,000 CAD in Year 2 and $2.4M CAD in Year 3. "
    "RateSift is production-ready, fully tested with 47 automated tests, and positioned to become the premier freight rate engine in Canada."
)

# -----------------------------------------------------------------------------
# SAVE PRESENTATION
# -----------------------------------------------------------------------------
output_path = os.path.abspath("RateSift_Platform_Presentation.pptx")
prs.save(output_path)
print(f"Presentation saved successfully to: {output_path}")

# Also save a copy in the artifact directory if accessible
artifact_dir = r"C:\Users\Dylan\.gemini\antigravity\brain\379ddefd-12de-409c-9457-0d28b0a07b22"
if os.path.exists(artifact_dir):
    artifact_copy = os.path.join(artifact_dir, "RateSift_Platform_Presentation.pptx")
    prs.save(artifact_copy)
    print(f"Copy saved to artifact directory: {artifact_copy}")
