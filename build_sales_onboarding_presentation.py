"""
build_sales_onboarding_presentation.py
====================================
Builds a 17-slide, casual-tone Sales Rep Onboarding PowerPoint presentation
for Quotelytics covering:
- Equity split (Class B Non-Voting milestone vesting) & 30% Year-1 commission structure
- What we're selling & the 4-tier pricing ladder (with BETA50 & FOUNDING25 promo codes)
- Business Tier Quoting (1/3): Master Formula & Variable Breakdown ($399 Base, Volume, Seats, Infra, Annual -20%)
- Business Tier Quoting (2/3): Why Degressive Volume Wins 3PL Deals (Plain-English Pitch & 300k Quote Example)
- Business Tier Quoting (3/3): 3 Sample Customer Quote Walkthroughs ($399, $874, $1,824) & 3-Click API Onboarding
- Step-by-step: How to quote in Quotelytics
- Complete FAQ for prospects & paying customers
- Advantages & disadvantages vs. Tabi Connect
- Reachout & CASL basics
- 10-Broker Private Beta plan, Beta Paperwork (Docs 11-13) & Pre-Beta Readiness Checklist
- Post-Beta roadmap & immediate action items
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

# -----------------------------------------------------------------------------
# BRAND DESIGN TOKENS (Matched to Quotelytics Brand System)
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
COLOR_AMBER_LIGHT = RGBColor(255, 251, 235)   # #FFFBEB

LOGO_PATH = os.path.abspath("static/images/quotelytics-logo.png")
OUTPUT_PATH = "Sales_Rep_Onboarding_Presentation.pptx"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
blank_layout = prs.slide_layouts[6]


def apply_background(slide, color=COLOR_WHITE):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_header(slide, title_text, category_text, slide_num_str):
    pill = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.36), Inches(3.2), Inches(0.32)
    )
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

    title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.74), Inches(9.6), Inches(0.7))
    tf = title_box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = title_text
    p.font.size = Pt(22)
    p.font.bold = True
    p.font.color.rgb = COLOR_SLATE_DARK

    if os.path.exists(LOGO_PATH):
        try:
            slide.shapes.add_picture(LOGO_PATH, Inches(10.55), Inches(0.38), height=Inches(0.35))
        except Exception:
            pass

    num_box = slide.shapes.add_textbox(Inches(12.0), Inches(0.38), Inches(0.6), Inches(0.35))
    p_num = num_box.text_frame.paragraphs[0]
    p_num.text = slide_num_str
    p_num.font.size = Pt(11)
    p_num.font.bold = True
    p_num.font.color.rgb = COLOR_SLATE_MUTED
    p_num.alignment = PP_ALIGN.RIGHT

    line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.48), Inches(11.733), Inches(0.02)
    )
    line.fill.solid()
    line.fill.fore_color.rgb = COLOR_BORDER
    line.line.fill.background()


def add_card(
    slide,
    left,
    top,
    width,
    height,
    title,
    bullets,
    accent_color=COLOR_RED_PRIMARY,
    bg_color=COLOR_SLATE_LIGHT,
    title_size=13.5,
    body_size=10.5,
    bullet_space=5,
):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = bg_color
    card.line.color.rgb = COLOR_BORDER
    card.line.width = Pt(1)

    accent = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        left + Inches(0.02),
        top + Inches(0.02),
        width - Inches(0.04),
        Inches(0.08),
    )
    accent.fill.solid()
    accent.fill.fore_color.rgb = accent_color
    accent.line.fill.background()

    tb = slide.shapes.add_textbox(
        left + Inches(0.22), top + Inches(0.18), width - Inches(0.44), height - Inches(0.28)
    )
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p_title = tf.paragraphs[0]
    p_title.text = title
    p_title.font.size = Pt(title_size)
    p_title.font.bold = True
    p_title.font.color.rgb = COLOR_SLATE_DARK
    p_title.space_after = Pt(bullet_space + 1)

    for item in bullets:
        p = tf.add_paragraph()
        p.space_after = Pt(bullet_space)
        p.font.size = Pt(body_size)
        if isinstance(item, tuple):
            lead, body = item
            r1 = p.add_run()
            r1.text = lead + " "
            r1.font.bold = True
            r1.font.color.rgb = COLOR_SLATE_DARK
            r2 = p.add_run()
            r2.text = body
            r2.font.color.rgb = COLOR_SLATE_MUTED
        else:
            p.text = "• " + item
            p.font.color.rgb = COLOR_SLATE_MUTED


def add_table(slide, left, top, width, height, headers, rows, col_widths=None, font_size=10):
    table_shape = slide.shapes.add_table(len(rows) + 1, len(headers), left, top, width, height)
    table = table_shape.table
    if col_widths:
        for idx, w in enumerate(col_widths):
            table.columns[idx].width = w

    for c_idx, h in enumerate(headers):
        cell = table.cell(0, c_idx)
        cell.fill.solid()
        cell.fill.fore_color.rgb = COLOR_SLATE_DARK
        p = cell.text_frame.paragraphs[0]
        p.text = h
        p.font.size = Pt(font_size + 0.5)
        p.font.bold = True
        p.font.color.rgb = COLOR_WHITE

    for r_idx, row_data in enumerate(rows):
        bg = COLOR_WHITE if r_idx % 2 == 0 else COLOR_SLATE_LIGHT
        for c_idx, val in enumerate(row_data):
            cell = table.cell(r_idx + 1, c_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg
            p = cell.text_frame.paragraphs[0]
            p.text = val
            p.font.size = Pt(font_size)
            p.font.bold = (c_idx == 0)
            p.font.color.rgb = COLOR_SLATE_DARK if c_idx == 0 else COLOR_SLATE_MUTED


def set_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


# =============================================================================
# SLIDE 1: TITLE SLIDE (Casual & Energetic)
# =============================================================================
s1 = prs.slides.add_slide(blank_layout)
apply_background(s1, COLOR_SLATE_DARK)

top_bar = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.1))
top_bar.fill.solid()
top_bar.fill.fore_color.rgb = COLOR_RED_PRIMARY
top_bar.line.fill.background()

if os.path.exists(LOGO_PATH):
    try:
        s1.shapes.add_picture(LOGO_PATH, Inches(0.9), Inches(0.95), height=Inches(0.62))
    except Exception:
        pass

badge = s1.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(1.95), Inches(4.8), Inches(0.38)
)
badge.fill.solid()
badge.fill.fore_color.rgb = COLOR_SLATE_NAVY
badge.line.color.rgb = COLOR_RED_PRIMARY
badge.line.width = Pt(1)
p_badge = badge.text_frame.paragraphs[0]
p_badge.text = "SALES ONBOARDING  •  10-BROKER BETA & LAUNCH"
p_badge.font.size = Pt(10)
p_badge.font.bold = True
p_badge.font.color.rgb = RGBColor(252, 165, 165)
p_badge.alignment = PP_ALIGN.CENTER

title_box = s1.shapes.add_textbox(Inches(0.9), Inches(2.55), Inches(11.4), Inches(1.4))
tf1 = title_box.text_frame
tf1.word_wrap = True
p_t1 = tf1.paragraphs[0]
p_t1.text = "Welcome to Quotelytics — Let's Launch This Thing"
p_t1.font.size = Pt(38)
p_t1.font.bold = True
p_t1.font.color.rgb = COLOR_WHITE

sub_box = s1.shapes.add_textbox(Inches(0.9), Inches(4.05), Inches(10.5), Inches(1.1))
tf_sub = sub_box.text_frame
tf_sub.word_wrap = True
p_sub = tf_sub.paragraphs[0]
p_sub.text = (
    "A complete walkthrough of how we split upside (30% commission + Class B milestone equity), what we're selling, "
    "the exact Business Tier Pricing Formula ($399+ base + degressive volume), customer FAQs, and our 10-Broker Beta Plan."
)
p_sub.font.size = Pt(15.5)
p_sub.font.color.rgb = RGBColor(203, 213, 225)

footer_box = s1.shapes.add_textbox(Inches(0.9), Inches(6.3), Inches(11.5), Inches(0.5))
p_f = footer_box.text_frame.paragraphs[0]
p_f.text = "Quotelytics Inc. (Federal CBCA)  |  https://quotelytics.ca  |  Founder + Sales Rep Onboarding Sync"
p_f.font.size = Pt(11)
p_f.font.color.rgb = COLOR_SLATE_MUTED

set_notes(
    s1,
    "Keep this session conversational. Goal is to make sure both reps feel 100% confident "
    "with the deal structure (Doc 13), the Business Tier Pricing Formula, the demo, and our 10-broker 30-day Beta plan."
)


# =============================================================================
# SLIDE 2: TODAY'S GAME PLAN
# =============================================================================
s2 = prs.slides.add_slide(blank_layout)
apply_background(s2)
add_header(s2, "What We're Covering Today (No Fluff)", "The Game Plan", "02/17")

add_card(
    s2,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(2.45),
    "1. How You Get Paid & Equity Split (Doc 13)",
    [
        "Independent Sales Rep Agreement: 30% Year-1 recurring cash commission + Class B Non-Voting milestone shares.",
        "Zero upfront dilution—shares unlock automatically at 5, 15, 30, and 50 active paying brokerages (or ARR equivalents).",
    ],
    accent_color=COLOR_EMERALD,
)

add_card(
    s2,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(2.45),
    "2. Pricing Ladder & Business Tier Formula",
    [
        "Self-serve tiers (Pro $79 / Team $199), promo codes (BETA50 / FOUNDING25), and our exact Business Tier Formula ($399/mo base).",
        "Plain-English pitch for Degressive Volume + 3 sample quote walkthroughs ($399, $874, $1,824/mo).",
    ],
    accent_color=COLOR_RED_PRIMARY,
)

add_card(
    s2,
    Inches(0.8),
    Inches(4.45),
    Inches(5.7),
    Inches(2.45),
    "3. Every Customer Question & Tabi Connect",
    [
        "Answers to every question a skeptical prospect or paying customer will throw at you.",
        "Honest look at where we beat Tabi Connect—and where they beat us.",
    ],
    accent_color=COLOR_INDIGO,
)

add_card(
    s2,
    Inches(6.8),
    Inches(4.45),
    Inches(5.733),
    Inches(2.45),
    "4. 10-Broker Beta Plan & Pre-Beta Checklist",
    [
        "Reachout cadence + CASL rules + Beta Participation & Testimonial forms (Docs 11 & 12).",
        "Exact checklist of what must be finished BEFORE Beta Day 1 vs. DURING the 30-day Beta.",
    ],
    accent_color=COLOR_AMBER,
)

set_notes(s2, "Quickly preview the flow so the reps know we'll cover money/equity first, then product + the exact Business Tier pricing formula, then beta readiness and execution.")


# =============================================================================
# SLIDE 3: EQUITY SPLIT & COMMISSION STRUCTURE
# =============================================================================
s3 = prs.slides.add_slide(blank_layout)
apply_background(s3)
add_header(s3, "How We Win Together: Commission & Milestone Equity (Doc 13)", "Comp & Equity", "03/17")

add_card(
    s3,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(3.25),
    "Cash Commission (30% of Year-1 Net Revenue)",
    [
        ("30% Recurring Commission:", "You earn 30% of Year-1 net subscription revenue collected from every brokerage you close (paid monthly)."),
        ("Standard Broker Pro ($79/mo):", "~$23.70 CAD/mo per account (or ~$11.85/mo on $39.50 BETA50; ~$16.59/mo on $55.30 FOUNDING25)."),
        ("Brokerage Team ($199/mo):", "~$59.70 CAD/mo per account (+30% on extra $25/mo seats)."),
        ("Business Tier ($399–$1,824+/mo):", "~$119.70 to $547+ CAD/mo per account (~$1,436 to $6,566+ CAD/yr from a single deal!)."),
    ],
    accent_color=COLOR_EMERALD,
    body_size=10,
)

add_card(
    s3,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(3.25),
    "Class B Non-Voting Milestone Equity",
    [
        ("0% Upfront; Pure Performance:", "Shares are Class B Non-Voting Common Shares (participate equally in any acquisition/exit)."),
        ("Milestone 1 (5 Paid Brokerages OR $5k ARR):", "Unlocks 250,000 Class B shares (~2.5% after 2 paid billing cycles)."),
        ("Milestone 2 (15 Paid Brokerages OR $15k ARR):", "Unlocks +250,000 Class B shares (~5.0% cumulative)."),
        ("Milestone 3 & Stretch (30–50 Brokerages / $30k–$50k ARR):", "Unlocks +350k at $30k ARR (~8.5%) and +150k at $50k ARR (~10.0% max cap)."),
    ],
    accent_color=COLOR_INDIGO,
    body_size=10,
)

banner3 = s3.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(5.25), Inches(11.733), Inches(1.55)
)
banner3.fill.solid()
banner3.fill.fore_color.rgb = COLOR_AMBER_LIGHT
banner3.line.color.rgb = COLOR_AMBER
banner3.line.width = Pt(1)
tb3 = banner3.text_frame
tb3.word_wrap = True
tb3.margin_left = Inches(0.3)
tb3.margin_right = Inches(0.3)
tb3.margin_top = Inches(0.22)
p3_1 = tb3.paragraphs[0]
p3_1.text = "Paperwork Ready to Sign Today (Doc 13 + Schedule 'A' $25 Demo Spiff):"
p3_1.font.size = Pt(13)
p3_1.font.bold = True
p3_1.font.color.rgb = COLOR_SLATE_DARK
p3_1.space_after = Pt(6)
p3_2 = tb3.add_paragraph()
p3_2.text = (
    "Doc 13 counts BOTH total accounts AND total ARR toward your equity milestones—and includes Schedule 'A': a $25 CAD cash spiff per Qualified Live Demo "
    "(up to 20 demos = $500 CAD/rep, funded from our $5,000 Ontario Starter Company Plus grant) when a prospect brings/uploads a real carrier sheet!"
)
p3_2.font.size = Pt(11)
p3_2.font.color.rgb = COLOR_SLATE_MUTED

set_notes(
    s3,
    "Highlight that milestones trigger on EITHER account count OR ARR ($5k / $15k / $30k / $50k). So closing larger Team or Business Tier accounts unlocks equity much faster."
)


# =============================================================================
# SLIDE 4: BREAKDOWN OF WHAT WE'RE SELLING
# =============================================================================
s4 = prs.slides.add_slide(blank_layout)
apply_background(s4)
add_header(s4, "What We're Actually Selling (Plain-English Breakdown)", "The Product", "04/17")

add_card(
    s4,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(5.1),
    "What Quotelytics Does",
    [
        ("Kills the 15-Min Spreadsheet Scramble:", "Canadian dispatchers spend 10–20 mins flipping through multi-tab LTL carrier Excel workbooks. We do it in <500ms."),
        ("100% Deterministic Excel Math:", "Calculates CWT weight breaks (L5C, M5C, M1M), deficit rating thresholds (e.g., 850 lbs rated at 1,000 lbs), and weekly diesel FSCs."),
        ("Exact Cell-Coordinate Proof:", "Every quote shows its exact source cell (e.g., Sheet 1 • Row 18, Col D). Zero AI guessing."),
        ("1-Click Client Proposal PDF:", "Add a brokerage markup (+10% / +15%) and export a clean, branded quote PDF for the shipper."),
        ("100% Canadian Data Sovereignty:", "Strictly tenant-isolated on Canadian servers (WHC Montreal/Vancouver) under PIPEDA."),
    ],
    accent_color=COLOR_RED_PRIMARY,
)

add_card(
    s4,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(2.45),
    "What Quotelytics Does NOT Do (Strict Boundary)",
    [
        ("No Truck Booking or Dispatching:", "We never book carriers, tender loads, or take freight commissions."),
        ("No Labels, BOLs, or Tracking:", "We strictly quote and compare LTL/skid rates—not parcel courier labels (UPS/FedEx)."),
    ],
    accent_color=COLOR_AMBER,
    bg_color=COLOR_AMBER_LIGHT,
)

add_card(
    s4,
    Inches(6.8),
    Inches(4.45),
    Inches(5.733),
    Inches(2.4),
    "Who We're Selling To (Canadian ICP)",
    [
        ("Brokerage Owners / Ops Directors:", "Small/mid-size Canadian 3PLs (1–20 dispatchers) who care about labor hours & data privacy."),
        ("Dispatch Managers & Lead Brokers:", "People quoting Ontario, Western & Atlantic Canada LTL lanes all day."),
        ("3PL Account Execs / Forwarders:", "Folks who want fast, branded shipper proposals without retyping Excel numbers."),
    ],
    accent_color=COLOR_SLATE_DARK,
)

set_notes(
    s4,
    "Keep the pitch simple: 'Upload your carrier Excel sheets once, type in origin/destination/weight, "
    "get every carrier ranked in half a second with exact cell proof.'"
)


# =============================================================================
# SLIDE 5: PRICING LADDER & PROMO OFFERS (BETA50 & FOUNDING25)
# =============================================================================
s5 = prs.slides.add_slide(blank_layout)
apply_background(s5)
add_header(s5, "The 4-Tier Pricing Ladder & Promo Codes (BETA50 & FOUNDING25)", "Pricing Ladder", "05/17")

add_table(
    s5,
    Inches(0.8),
    Inches(1.75),
    Inches(11.733),
    Inches(3.2),
    ["Subscription Tier", "Monthly Price (CAD)", "Annual Price (-20%)", "Included Quotes / Mo", "Included Seats", "Effective Cost / Quote"],
    [
        ["Free Starter", "$0 / mo", "$0 / mo", "50 quotes\n(Up to 3 rate sheets)", "1 seat", "$0.000"],
        ["Broker Pro\n(Main Beta Target)", "$79 / mo\n($39.50 w/ BETA50)\n($55.30 w/ FOUNDING25)", "$63 / mo", "2,500 quotes\n(Up to 10 rate sheets)", "1 seat", "$0.031 (3.1¢)"],
        ["Broker Team", "$199 / mo", "$159 / mo", "15,000 quotes\n(Unlimited sheets)", "5 seats\n(+$25 / extra)", "$0.013 (1.3¢)"],
        ["Business Tier\n(Embedded API)", "From $399 / mo", "From $319 / mo", "50,000+ API quotes\n(Unlimited sheets & keys)", "10 seats\n(+$20 / extra)", "< $0.008 (0.8¢)"],
    ],
    col_widths=[Inches(2.1), Inches(2.4), Inches(1.9), Inches(2.2), Inches(1.5), Inches(1.633)],
    font_size=9.5,
)

promo5 = s5.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(5.2), Inches(11.733), Inches(1.6)
)
promo5.fill.solid()
promo5.fill.fore_color.rgb = COLOR_RED_LIGHT
promo5.line.color.rgb = COLOR_RED_PRIMARY
promo5.line.width = Pt(1)
tb5 = promo5.text_frame
tb5.word_wrap = True
tb5.margin_left = Inches(0.3)
tb5.margin_right = Inches(0.3)
tb5.margin_top = Inches(0.18)
p5_1 = tb5.paragraphs[0]
p5_1.text = "How Our Two Promo Codes Work (Both Wired in Stripe):"
p5_1.font.size = Pt(13)
p5_1.font.bold = True
p5_1.font.color.rgb = COLOR_RED_DARK
p5_1.space_after = Pt(5)
p5_2 = tb5.add_paragraph()
p5_2.text = (
    "• BETA50 (10-Broker Beta Cohort Only): 30 days 100% FREE, then 50% OFF Broker Pro for 12 months ($39.50 CAD/mo instead of $79 — saves $474/yr). "
    "Earned by completing the beta (2 quick feedback calls + exit survey)—NOT contingent on a positive review.\n"
    "• FOUNDING25 (First 25 Public Customers After Beta): 30% OFF Broker Pro for 12 months ($55.30 CAD/mo instead of $79)."
)
p5_2.font.size = Pt(10.5)
p5_2.font.color.rgb = COLOR_SLATE_DARK

set_notes(s5, "Notice how our deterministic Python engine + in-memory 1,600+ Canadian FSAs give us $0 LLM token costs and $0 Google Maps fees—allowing us to drop per-quote cost from 3.1¢ on Pro down to <0.8¢ on Business Tier!")


# =============================================================================
# SLIDE 6: BUSINESS TIER QUOTING (1/3) — THE MASTER FORMULA & VARIABLES
# =============================================================================
s6_f = prs.slides.add_slide(blank_layout)
apply_background(s6_f)
add_header(s6_f, "Business Tier Quoting (1/3): Master Formula & Variables", "Enterprise Pricing", "06/17")

f_banner = s6_f.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.65), Inches(11.733), Inches(0.78)
)
f_banner.fill.solid()
f_banner.fill.fore_color.rgb = COLOR_SLATE_DARK
f_banner.line.color.rgb = COLOR_RED_PRIMARY
f_banner.line.width = Pt(1.5)
tf_fb = f_banner.text_frame
tf_fb.word_wrap = True
tf_fb.margin_top = Inches(0.1)
p_fb1 = tf_fb.paragraphs[0]
p_fb1.text = "Monthly Quote (CAD)  =  ( B_platform  +  C_volume  +  C_seats  +  C_infra )  ×  ( 1 − D_annual )"
p_fb1.font.size = Pt(14)
p_fb1.font.bold = True
p_fb1.font.color.rgb = COLOR_WHITE
p_fb1.alignment = PP_ALIGN.CENTER
p_fb2 = tf_fb.add_paragraph()
p_fb2.text = "Plus optional 1-time tariff onboarding fee (F_setup = $15 CAD/sheet past first 10 free sheets) — 100% WAIVED on annual contracts (-20% D_annual)."
p_fb2.font.size = Pt(9.5)
p_fb2.font.color.rgb = RGBColor(203, 213, 225)
p_fb2.alignment = PP_ALIGN.CENTER

add_card(
    s6_f,
    Inches(0.8),
    Inches(2.58),
    Inches(5.7),
    Inches(2.15),
    "1. Base Platform (B_platform = $399/mo) & Seats (C_seats)",
    [
        ("B_platform ($399 CAD/mo):", "Includes 50,000 quotes/mo (web + REST API), 10 dispatcher UI seats, unlimited rate sheets & API keys, <350ms SLA & webhooks."),
        ("Extra Seats (C_seats = $20 × max(0, S − 10)):", "$20/seat above 10 seats (drops to $15/seat above 25 seats). Zero seat tax on API portal traffic!"),
        ("Annual Discount (D_annual = 20%):", "20% off all recurring components via Canadian PAD/EFT + waives $15/sheet setup fee past 10 free sheets."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    title_size=12,
    body_size=9.2,
    bullet_space=3,
)

add_card(
    s6_f,
    Inches(0.8),
    Inches(4.88),
    Inches(5.7),
    Inches(2.1),
    "2. Enterprise Infrastructure & White-Label Add-Ons (C_infra)",
    [
        ("Logical Canadian Tenant (WHC Shared Cluster):", "$0 / mo (Included — strict user_id PIPEDA quarantine in Canada)."),
        ("Dedicated Isolated Canadian Cloud Tenant (WHC):", "+$150 / mo (Isolated VPS/container & dedicated DB instance in Canada)."),
        ("White-Label Client Proposal & Portal API:", "+$75 / mo (Removes Quotelytics branding on Excel/PDFs; injects 3PL logo & domain)."),
        ("Custom Carrier Formula / ERP Connector:", "+$50 / mo per carrier (Bespoke carrier rules or custom ERP webhooks)."),
    ],
    accent_color=COLOR_INDIGO,
    title_size=12,
    body_size=9.2,
    bullet_space=3,
)

vol_label = s6_f.shapes.add_textbox(Inches(6.8), Inches(2.58), Inches(5.733), Inches(0.35))
p_vl = vol_label.text_frame.paragraphs[0]
p_vl.text = "3. Marginal Quote Volume Scaling (C_volume — Degressive Per-1k Blocks)"
p_vl.font.size = Pt(12)
p_vl.font.bold = True
p_vl.font.color.rgb = COLOR_SLATE_DARK

add_table(
    s6_f,
    Inches(6.8),
    Inches(2.95),
    Inches(5.733),
    Inches(2.6),
    ["Monthly Quote Bracket (Q)", "Marginal Price / 1k", "Effective Rate", "Formula Segment"],
    [
        ["0 – 50,000 quotes", "Included in $399 Base", "$0.0080 (0.8¢)", "$0"],
        ["50,001 – 250,000 quotes", "+$4.00 CAD / 1,000", "$0.0040 (0.4¢)", "4 × ((min(Q, 250k) - 50k) / 1,000)"],
        ["250,001 – 1,000,000 quotes", "+$2.00 CAD / 1,000", "$0.0020 (0.2¢)", "2 × ((min(Q, 1M) - 250k) / 1,000)"],
        ["1,000,000+ quotes", "+$1.00 CAD / 1,000", "$0.0010 (0.1¢)", "1 × ((Q - 1,000k) / 1,000)"],
    ],
    col_widths=[Inches(1.65), Inches(1.4), Inches(1.05), Inches(1.633)],
    font_size=8.8,
)

add_card(
    s6_f,
    Inches(6.8),
    Inches(5.7),
    Inches(5.733),
    Inches(1.28),
    "Why Degressive Volume Wins Deals (See Full Pitch on Next Slide)",
    [
        ("Never Penalizes High-Traffic 3PL Portals:", "Instead of a flat per-quote tax, volume above 50k/mo drops in half at each tier: 0.8¢ -> 0.4¢ -> 0.2¢ -> 0.1¢ per quote."),
    ],
    accent_color=COLOR_EMERALD,
    title_size=11.5,
    body_size=9.2,
    bullet_space=2,
)

set_notes(
    s6_f,
    "Walk reps through the 4 building blocks of the Business Tier formula: "
    "$399 Base (50k quotes + 10 seats) + Volume blocks (+$4/1k from 50k-250k, +$2/1k from 250k-1M, +$1/1k above 1M) + Extra seats ($20/seat past 10) + Infra add-ons, with 20% off for annual PAD/EFT."
)


# =============================================================================
# SLIDE 7: BUSINESS TIER QUOTING (2/3) — WHY DEGRESSIVE VOLUME WINS 3PL DEALS
# =============================================================================
s7_deg = prs.slides.add_slide(blank_layout)
apply_background(s7_deg)
add_header(s7_deg, "Business Tier Quoting (2/3): Why Degressive Volume Wins Deals", "Degressive Volume Pitch", "07/17")

add_card(
    s7_deg,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(3.25),
    "1. The Problem With 'Flat Per-Quote' Pricing on Portals",
    [
        ("Lookups != Booked Loads:", "When a 3PL puts our Embedded API on their customer website, a shipper often runs 20–30 weight/postal lookups ('What about 2 skids Tuesday vs. 4 skids Friday?') before booking 1 actual truck."),
        ("The 'Traffic Tax' Fear:", "If a software vendor charges a flat 1¢–3¢ per API call, a 3PL running 300,000 portal lookups/mo gets hit with a scary $3,000–$9,000/mo bill just because shippers were browsing."),
        ("How We Remove That Fear:", "Degressive volume means the more quotes they run, the cheaper each extra quote gets—cutting in half at every bracket (0.8¢ -> 0.4¢ -> 0.2¢ -> 0.1¢)."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    title_size=12.5,
    body_size=9.6,
    bullet_space=4,
)

add_card(
    s7_deg,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(3.25),
    "2. Live Sales Call Math: 300,000 Portal Quotes / Month",
    [
        ("Under a Flat 0.8¢ Rate:", "300,000 quotes × $0.008 = $2,400 / mo (Too expensive for portal browsing!)."),
        ("Under Our Degressive Formula:", "• First 50,000 quotes (0–50k) = $399 (Included in Base)"),
        ("Next 200,000 Quotes (50k–250k @ $4/1k):", "• 200 × $4.00 = $800 (Drops in half to 0.4¢ / quote)"),
        ("Final 50,000 Quotes (250k–300k @ $2/1k):", "• 50 × $2.00 = $100 (Drops in half again to 0.2¢ / quote)"),
        ("Total Quote Volume Cost:", "$1,299 / mo instead of $2,400 / mo — saves the 3PL $1,100+/mo!"),
    ],
    accent_color=COLOR_EMERALD,
    title_size=12.5,
    body_size=9.6,
    bullet_space=4,
)

secret_banner = s7_deg.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(5.2), Inches(11.733), Inches(1.65)
)
secret_banner.fill.solid()
secret_banner.fill.fore_color.rgb = COLOR_SLATE_DARK
secret_banner.line.color.rgb = COLOR_INDIGO
secret_banner.line.width = Pt(1.5)
tb_sec = secret_banner.text_frame
tb_sec.word_wrap = True
tb_sec.margin_left = Inches(0.3)
tb_sec.margin_right = Inches(0.3)
tb_sec.margin_top = Inches(0.2)
p_sec1 = tb_sec.paragraphs[0]
p_sec1.text = "3. Why We Can Afford This (Your Secret Weapon on Enterprise Calls):"
p_sec1.font.size = Pt(13)
p_sec1.font.bold = True
p_sec1.font.color.rgb = RGBColor(252, 165, 165)
p_sec1.space_after = Pt(5)
p_sec2 = tb_sec.add_paragraph()
p_sec2.text = (
    "Competitors that rely on AI/LLMs or pay Google Maps per lookup get billed by third parties every time a user clicks 'Quote'—so their costs climb linearly. "
    "Because Quotelytics runs 100% deterministic Python math and keeps all 1,600+ Canadian Postal FSAs in memory on our WHC server, "
    "300,000 API quotes costs us almost $0 in extra compute—letting us pass huge bulk savings to the 3PL while keeping 85%+ margins (and paying your full 30% commission!)."
)
p_sec2.font.size = Pt(10.5)
p_sec2.font.color.rgb = RGBColor(226, 232, 240)

set_notes(
    s7_deg,
    "Use this exact 300,000-quote example whenever a 3PL asks 'What if our shippers spam the rate calculator on our website?' "
    "Show them how the rate drops from 0.8¢ to 0.4¢ to 0.2¢ to 0.1¢."
)


# =============================================================================
# SLIDE 8: BUSINESS TIER QUOTING (3/3) — 3 SAMPLE WALKTHROUGHS & ONBOARDING
# =============================================================================
s7_w = prs.slides.add_slide(blank_layout)
apply_background(s7_w)
add_header(s7_w, "Business Tier Quoting (3/3): 3 Sample Walkthroughs & Onboarding", "Sample Quotes", "08/17")

add_table(
    s7_w,
    Inches(0.8),
    Inches(1.7),
    Inches(11.733),
    Inches(2.6),
    ["Customer Profile", "Configuration Inputs", "Formula Calculation (Monthly)", "Monthly Billing", "Annual Billing (-20%)"],
    [
        [
            "1. Mid-Size Brokerage",
            "50k quotes/mo, 10 seats,\nShared WHC tenant, Standard PDFs",
            "$399 (Base) + $0 (Volume)\n+ $0 (Seats) + $0 (Infra)",
            "$399 CAD / mo\n(Rep 30%: ~$119.70/mo)",
            "$319 CAD / mo\n($3,830 / yr)"
        ],
        [
            "2. Growing 3PL Portal",
            "125k quotes/mo, 15 seats,\nWhite-Label API (+$75), Shared tenant",
            "$399 (Base) + $300 (75k extra quotes)\n+ $100 (5 extra seats) + $75 (White-Label)",
            "$874 CAD / mo\n(Rep 30%: ~$262.20/mo)",
            "$699 CAD / mo\n($8,390 / yr)"
        ],
        [
            "3. Enterprise 3PL Network",
            "300k quotes/mo, 25 seats, Dedicated\nWHC Server (+$150), White-Label (+$75)",
            "$399 (Base) + $900 (250k extra quotes)\n+ $300 (15 extra seats) + $225 (Infra)",
            "$1,824 CAD / mo\n(Rep 30%: ~$547.20/mo)",
            "$1,459 CAD / mo\n($17,510 / yr)"
        ],
    ],
    col_widths=[Inches(2.0), Inches(2.7), Inches(3.233), Inches(1.9), Inches(1.9)],
    font_size=9.2,
)

add_card(
    s7_w,
    Inches(0.8),
    Inches(4.5),
    Inches(5.7),
    Inches(2.45),
    "4 Questions to Ask on a Business Tier Discovery Call",
    [
        ("1. Monthly API Quote Volume (Q):", "How many quotes/mo will your portal + dispatchers run? (First 50k included in $399 base)."),
        ("2. Human Dispatcher Logins (S):", "How many human dispatchers need UI logins? (First 10 included; +$20/extra seat; API traffic is seat-free)."),
        ("3. Infrastructure & Branding (C_infra):", "Need White-Label PDFs (+$75/mo), Dedicated WHC Server (+$150/mo), or Custom ERP Connector (+$50/carrier)?"),
        ("4. Billing & Setup (D_annual & F_setup):", "Pitch Annual PAD/EFT (-20% discount + waives the $15/sheet tariff setup fee beyond the first 10 free sheets!)."),
    ],
    accent_color=COLOR_INDIGO,
    title_size=12,
    body_size=9.3,
    bullet_space=3,
)

add_card(
    s7_w,
    Inches(6.8),
    Inches(4.5),
    Inches(5.733),
    Inches(2.45),
    "3-Click Zero-Code Onboarding (/console/admin)",
    [
        ("Step 1 — Unlock Business Tier:", "Once payment/PAD is set up, open /console/admin, search the customer's email, and click 'Activate Business'."),
        ("Step 2 — Live Zoom Self-Test:", "Customer opens /console/account#api, clicks 'Generate API Key', and clicks 'Verify My API Setup' (runs live quote in <50ms)."),
        ("Step 3 — 1-Click IT Handoff:", "Click 'Copy Email for IT Team' to send ready-made endpoints (POST /api/v1/quotes/batch) & Swagger docs to their developer."),
    ],
    accent_color=COLOR_EMERALD,
    title_size=12,
    body_size=9.5,
    bullet_space=4,
)

set_notes(
    s7_w,
    "Show how Profile 3 (300k quotes/mo) calculates C_volume: 200k quotes in the 50k–250k bracket at $4/1k ($800) + 50k quotes in the 250k–1M bracket at $2/1k ($100) = $900 volume charge."
)


# =============================================================================
# SLIDE 9: HOW TO QUOTE IN QUOTELYTICS (STEP-BY-STEP)
# =============================================================================
s6 = prs.slides.add_slide(blank_layout)
apply_background(s6)
add_header(s6, "How to Quote in Quotelytics (5-Step Live Walkthrough)", "How to Quote", "09/17")

steps = [
    ("1. Upload / Concierge", COLOR_INDIGO, [
        "Go to /console/rate-sheets.",
        "Pick a Canadian Carrier Preset (Manitoulin, Day & Ross, etc.) OR drop up to 10 sheets into the 24-Hr Concierge Drop-Box!",
    ]),
    ("2. Confirm & Accessorials", COLOR_EMERALD, [
        "Auto-maps 150+ Canadian cities to FSAs (Mississauga -> L5T).",
        "Set Big 6 Accessorials (Tailgate, Winter Heated +15% / $45 min, Residential, Appt).",
    ]),
    ("3. Smart Email Paste", COLOR_RED_PRIMARY, [
        "Go to /console/new-quote.",
        "Paste raw shipper email into ⚡ 1-Second Smart Paste—auto-fills Lane, Weight, Skids & Tailgate/Heated checkboxes!",
    ]),
    ("4. Audit Math", COLOR_SLATE_DARK, [
        "View carriers ranked lowest to highest (<500ms).",
        "Click a quote to open Audit Drawer: shows Base, FSC, Deficit & 'Sheet 1 • Row 18, Col D'.",
    ]),
    ("5. Export PDF", COLOR_AMBER, [
        "Toggle brokerage markup (+10% or +15%).",
        "Click Export Client Proposal PDF to generate a clean, shipper-ready quote.",
    ]),
]

x_p = Inches(0.8)
w_card = Inches(2.22)
g_card = Inches(0.158)
for st_title, st_col, st_bullets in steps:
    add_card(s6, x_p, Inches(1.75), w_card, Inches(4.15), st_title, st_bullets, accent_color=st_col, title_size=12.5, body_size=9.8)
    x_p += w_card + g_card

tip6 = s6.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(6.12), Inches(11.733), Inches(0.75)
)
tip6.fill.solid()
tip6.fill.fore_color.rgb = COLOR_SLATE_DARK
tip6.line.fill.background()
p6 = tip6.text_frame.paragraphs[0]
p6.text = "PRO TIP FOR DEMOS: Always keep https://quotelytics.ca/demo open in another tab as a zero-signup backup if a prospect forgot to bring a spreadsheet!"
p6.font.size = Pt(11.5)
p6.font.bold = True
p6.font.color.rgb = COLOR_WHITE
p6.alignment = PP_ALIGN.CENTER

set_notes(s6, "Walk the reps through quotelytics.ca/demo right after this deck so they see these exact 5 steps in action.")


# =============================================================================
# SLIDE 10: PROSPECT & BETA CUSTOMER FAQ
# =============================================================================
s7 = prs.slides.add_slide(blank_layout)
apply_background(s7)
add_header(s7, "Every Question a Prospect or Beta Tester Will Ask", "Customer FAQ (1/2)", "10/17")

add_card(
    s7,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(5.1),
    "Product & Trust Questions",
    [
        ("Q: Does AI guess or estimate our rates?", "No. 100% deterministic math directly from your confirmed Excel cells. Every dollar links to its exact row/column."),
        ("Q: Do you book trucks or take a commission?", "Never. Zero carrier lock-in, zero commissions. We only quote and compare rates."),
        ("Q: Is our carrier rate data safe / shared?", "100% private and tenant-isolated on Canadian servers (Montreal & Vancouver) under PIPEDA. Nobody else ever sees your rates."),
        ("Q: What file formats do you support?", "Standard .xlsx, .xls, and .csv carrier tariffs across Canadian & cross-border LTL and skid carriers."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    body_size=10,
)

add_card(
    s7,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(5.1),
    "Workflow & Fit Questions",
    [
        ("Q: We already have a TMS—why do we need this?", "TMS platforms rarely handle messy multi-tab carrier Excel tariffs cleanly. Quotelytics sits beside your TMS for 500ms quoting (or plugs in via API)."),
        ("Q: Can it handle deficit rating & fuel surcharges?", "Yes—L5C/M5C/M1M weight breaks, deficit thresholds, and weekly diesel FSC indices are built in."),
        ("Q: How long does it take to set up?", "Under 5 minutes to upload your first sheet. During beta, we also offer white-glove calibration within 4 hours."),
        ("Q: Does it do parcel (UPS/FedEx) or labels?", "No. Built strictly for Canadian & cross-border LTL and skid/pallet freight quoting."),
    ],
    accent_color=COLOR_SLATE_DARK,
    body_size=10,
)

set_notes(s7, "Have reps memorize these 8 answers—90% of cold call and demo questions will be one of these.")


# =============================================================================
# SLIDE 11: PAYING CUSTOMER FAQ (PRO, TEAM & BUSINESS)
# =============================================================================
s8 = prs.slides.add_slide(blank_layout)
apply_background(s8)
add_header(s8, "Every Question a Paying Customer Will Ask", "Customer FAQ (2/2)", "11/17")

add_card(
    s8,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(5.1),
    "Billing, Seats & Plan Questions",
    [
        ("Q: What happens if I hit 50 quotes on Free Starter?", "You can upgrade to Broker Pro ($79 CAD/mo, $39.50 with BETA50, or $55.30 with FOUNDING25) anytime for up to 10 sheets & 2,500 quotes/mo."),
        ("Q: How do extra seats work on Team vs. Business?", "Team ($199/mo) includes 5 seats (+$25/extra). Business ($399+/mo) includes 10 seats (+$20/extra, or +$15/seat above 25 seats)."),
        ("Q: Do customer portal API calls require dispatcher seats?", "No! Zero seat tax on API traffic—portal calls only consume monthly quote volume (Q)."),
        ("Q: What if we downgrade off Business Tier?", "API keys pause immediately until Business Tier is reactivated, so there are no surprise overages."),
    ],
    accent_color=COLOR_INDIGO,
    body_size=10,
)

add_card(
    s8,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(5.1),
    "Business Tier API & Technical Questions",
    [
        ("Q: How fast & big is the Business API?", "Sub-350ms latency SLA (<50ms typical), 1–100 shipments per batch call, 50,000+ quotes/mo base, unlimited sheets & API keys."),
        ("Q: Does the API apply our broker markup?", "Yes, automatically from your Settings—and your IT team can override or disable markup per API request."),
        ("Q: Do I need to code anything on the onboarding call?", "No! Zero coding for sales reps. 3 clicks: Activate Business Plan -> Customer clicks 'Verify My API Setup' -> Click 'Copy Email for IT Team'."),
        ("Q: Where are API docs for our developer?", "Interactive Swagger docs live at https://quotelytics.ca/docs."),
    ],
    accent_color=COLOR_EMERALD,
    body_size=10,
)

set_notes(s8, "Remind reps: for any deep API troubleshooting, refer to outreach/08_Sales_Rep_Business_API_Setup_and_Troubleshooting_Guide.docx.")


# =============================================================================
# SLIDE 12: COMPETITIVE COMPARISON — QUOTELYTICS VS. TABI CONNECT
# =============================================================================
s9 = prs.slides.add_slide(blank_layout)
apply_background(s9)
add_header(s9, "How We Stack Up Against Tabi Connect (Be Honest)", "Competitive Intel", "12/17")

add_card(
    s9,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(4.3),
    "Where Quotelytics Wins (Our Advantages)",
    [
        ("100% Deterministic Excel Cell Math:", "We quote directly from the broker's confirmed carrier spreadsheets with exact cell proof (Sheet 1 • Row 18, Col D). Tabi leans on AI extraction & dynamic market rules."),
        ("Built for Canadian LTL & Deficit Math:", "Purpose-built for Canadian FSAs (M5V -> T2P), CWT breaks (L5C/M5C/M1M), and deficit rating—not generic US spot boards."),
        ("100% Canadian Data Sovereignty:", "Strictly hosted in Canadian data centres under PIPEDA. Huge win for privacy-conscious Canadian 3PLs."),
        ("Transparent SMB Pricing & 15-Min Setup:", "$0 Free Starter / $79 Pro ($39.50 BETA50). Live in 15 mins with zero enterprise RPA setup fees."),
    ],
    accent_color=COLOR_EMERALD,
    body_size=9.8,
)

add_card(
    s9,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(4.3),
    "Where Tabi Connect Wins (Our Disadvantages)",
    [
        ("No Email / Bid-Board / Portal Ingestion:", "Tabi uses AI & RPA to auto-read quote requests from email inboxes and 70–80+ shipper portals. With Quotelytics, the broker (or Business API) inputs the lane."),
        ("No Auto-Reply or TMS Load Push:", "Tabi can auto-reply to shippers and push awarded loads into a core TMS. Quotelytics strictly quotes & compares (PDF export or Business API JSON)."),
        ("No Spot/Market Rate Benchmarking:", "Tabi prices against live market/historical spot data; Quotelytics only quotes from the carrier Excel tariffs you upload."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    bg_color=COLOR_RED_LIGHT,
    body_size=9.8,
)

comp_note = s9.shapes.add_shape(
    MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(6.22), Inches(11.733), Inches(0.65)
)
comp_note.fill.solid()
comp_note.fill.fore_color.rgb = COLOR_SLATE_DARK
comp_note.line.fill.background()
p_cn = comp_note.text_frame.paragraphs[0]
p_cn.text = "HOW TO POSITION IT: Tabi Connect is great for large brokers automating high-volume email/portal bid boards. Quotelytics is for Canadian LTL desks that want fast, exact, auditable math from their own carrier Excel tariffs."
p_cn.font.size = Pt(10.5)
p_cn.font.bold = True
p_cn.font.color.rgb = COLOR_WHITE
p_cn.alignment = PP_ALIGN.CENTER

set_notes(s9, "Never trash-talk Tabi Connect. Acknowledge what they do well (AI email/portal RPA) and pivot to what Canadian LTL brokers actually need: fast, exact, auditable Excel tariff math at a fraction of the cost.")


# =============================================================================
# SLIDE 13: REACHOUT CADENCE & CASL RULES
# =============================================================================
s10 = prs.slides.add_slide(blank_layout)
apply_background(s10)
add_header(s10, "The Reachout Phase: Weekly Rhythm & CASL Rules", "Outreach & Legal", "13/17")

add_card(
    s10,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(5.1),
    "Weekly Outreach Rhythm (All Templates Ready)",
    [
        ("Tuesday 8:30 AM — Owners / Ops (Template 1):", "Focus on labor savings & Canadian data residency. Goal: book Thu/Fri demos."),
        ("Wednesday 9:00 AM — Dispatchers (Template 2):", "Focus on CWT/deficit math & drive clicks to quotelytics.ca/demo."),
        ("Thursday 2:00 PM — 3PL AEs (Template 3):", "Focus on 1-click Client Proposal PDFs & markup toggles."),
        ("LinkedIn + 1x Follow-Up Rule:", "Pair with Tue/Thu LinkedIn posts. Send exactly ONE polite follow-up 3–4 business days later if no reply."),
        ("Target List (Outside Quebec for Beta):", "Use Canadian_Freight_Brokerage_Target_Prospects.xlsx—focus on ON, AB, BC, MB & Atlantic Canada for Cohort 1."),
    ],
    accent_color=COLOR_INDIGO,
    body_size=10,
)

add_card(
    s10,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(5.1),
    "4 Non-Negotiable CASL Rules (Canada)",
    [
        ("1. Conspicuously Published Email Only:", "Only cold-email addresses publicly listed on company websites, directories, or LinkedIn—with no 'do not solicit' notice."),
        ("2. Direct Business Role Relevance:", "Message must clearly match their job (dispatch, LTL pricing, brokerage ops)."),
        ("3. Full Sender Identification:", "Every email must include 'Quotelytics Inc.', physical Ontario mailing address, support@quotelytics.ca, and 289-929-8565."),
        ("4. Working 1-Click Unsubscribe:", "Every email must include https://quotelytics.ca/unsubscribe?email={{email}} and opt-outs must be honored immediately."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    bg_color=COLOR_RED_LIGHT,
    body_size=10,
)

set_notes(s10, "Double-check that the physical mailing address placeholder in the email templates is filled in before sending wave 1, and keep Cohort 1 outside Quebec because of Bill 96 French-language rules.")


# =============================================================================
# SLIDE 14: THE 10-BROKER PRIVATE BETA PLAN & PAPERWORK
# =============================================================================
s11 = prs.slides.add_slide(blank_layout)
apply_background(s11)
add_header(s11, "The 10-Broker Private Beta Plan (4 Weeks) & Paperwork", "Beta Plan", "14/17")

add_card(
    s11,
    Inches(0.8),
    Inches(1.75),
    Inches(3.75),
    Inches(4.95),
    "1. 10-Broker Cohort & Paperwork",
    [
        ("10 Beta Brokerages:", "Recruit 10 Canadian LTL brokerages (5 managed by each rep) for a 30-day free Broker Pro beta."),
        ("Beta Agreement (Doc 11):", "Each tester signs 11_Beta_Participation_Agreement.docx (1–3 real tariffs, weekly use, two 15-min calls)."),
        ("BETA50 Reward ($39.50/mo):", "Completing the beta unlocks 50% off Broker Pro for 12 months (earned by participation, not a forced review)."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    body_size=9.8,
)

add_card(
    s11,
    Inches(4.78),
    Inches(1.75),
    Inches(3.75),
    Inches(4.95),
    "2. Week 1 & Week 4 Calls",
    [
        ("Week 1 Onboarding (15 Min):", "Run Doc 07 script—upload first Excel tariff, pass Confirmation Gate, run live lane quote & export PDF."),
        ("Weeks 2–3 Check-Ins:", "White-glove calibration within 4 hours for any messy carrier sheets; track deficit-rating catches."),
        ("Week 4 Exit Call (15 Min):", "Run 5-question exit survey & capture verified time-savings metrics."),
    ],
    accent_color=COLOR_EMERALD,
    body_size=9.8,
)

add_card(
    s11,
    Inches(8.76),
    Inches(1.75),
    Inches(3.773),
    Inches(4.95),
    "3. Testimonial Release (Doc 12)",
    [
        ("Consent Form (Doc 12):", "Happy testers sign 12_Testimonial_and_Logo_Consent_Form.docx on the Week-4 call."),
        ("3 Attribution Levels:", "Option A: Name + Title + Company + Logo  •  Option B: Name + Company (no logo)  •  Option C: Anonymized region."),
        ("Competition Act Rule:", "We disclose 'Founding Beta Participant — received discounted subscription' next to published quotes."),
    ],
    accent_color=COLOR_INDIGO,
    body_size=9.8,
)

set_notes(s11, "Every beta tester signs Doc 11 at the start of the 30-day beta, and happy testers sign Doc 12 at the Week-4 exit call.")


# =============================================================================
# SLIDE 15: WHAT ELSE NEEDS TO BE DONE BEFORE & DURING BETA
# =============================================================================
s12 = prs.slides.add_slide(blank_layout)
apply_background(s12)
add_header(s12, "Beta Prep Checklist: What Happens Before vs. During Beta", "Beta Readiness", "15/17")

add_card(
    s12,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(5.1),
    "Part 1: Must Be Done BEFORE Beta Day 1 (5 Items)",
    [
        ("1. WHC Canadian Server & Email Live:", "Order WHC Cloud VPS (2 vCPU / 4 GB RAM + Backups), point quotelytics.ca SSL, set up support@quotelytics.ca, and run 1 end-to-end test signup."),
        ("2. File Federal (CBCA) Incorporation ($200):", "Order Federal NUANS ($13.80) + file Form 1/Form 2 online (Doc 01) + Free Joint Ontario Registration ($0) + ISC filing."),
        ("3. Sign Sales Rep Agreements (Doc 13):", "Execute 13_Independent_Sales_Rep_and_Milestone_Equity_Agreement.docx with both sales reps."),
        ("4. Get Tech E&O + Cyber Insurance Quotes:", "Request quotes from Zensurance / APOLLO before testers upload confidential carrier rate sheets."),
        ("5. Recruit 10 Beta Testers (Outside Quebec):", "Sign 10 brokerages onto 11_Beta_Participation_Agreement.docx and book Week-1 onboarding calls."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    body_size=9.6,
)

add_card(
    s12,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(5.1),
    "Part 2: Done in Parallel DURING the 30-Day Free Beta",
    [
        ("1. Sign Minute Book & IP Assignment (Docs 02–09):", "Insert the Federal Corp Number into the CBCA Minute Book and sign the IP Assignment (Dylan -> Quotelytics Inc.)."),
        ("2. Open Corporate Bank Account (Doc 07):", "Open business account (RBC / TD / Venn) using Certificate of Incorporation, BN, and Certified Banking Resolution."),
        ("3. Register GST/HST & Activate Stripe Live Mode:", "Connect corporate bank account to Stripe Canada, enable Stripe Tax (GST/HST), and activate live BETA50 & FOUNDING25 coupons before Day 30."),
        ("4. Apply for $5,000 Starter Company Plus Grant:", "Book local Ontario SBEC orientation and submit Starter_Company_Plus_Business_Plan_Quotelytics.docx."),
        ("5. Collect 3+ Signed Testimonial Releases (Doc 12):", "Gather signed logo/quote releases in Week 4 and convert beta testers onto BETA50 ($39.50 CAD/mo)."),
    ],
    accent_color=COLOR_EMERALD,
    body_size=9.6,
)

set_notes(
    s12,
    "Because the 30-day beta is 100% free ($0), we don't need live Stripe credit-card processing on Day 1 of the beta. "
    "We only need the live WHC site, Federal CBCA incorporation, signed rep & beta agreements, and our 10 testers!"
)


# =============================================================================
# SLIDE 16: NEXT STEPS AFTER THE BETA (PAID LAUNCH & GROWTH)
# =============================================================================
s13 = prs.slides.add_slide(blank_layout)
apply_background(s13)
add_header(s13, "What Happens After Beta: Paid Launch & Growth Roadmap", "Post-Beta Roadmap", "16/17")

add_card(
    s13,
    Inches(0.8),
    Inches(1.75),
    Inches(5.7),
    Inches(2.45),
    "Phase 1: Day 30 Beta Conversion & Public Launch",
    [
        ("Convert Beta Cohort (BETA50):", "Move the 10 beta testers onto Broker Pro at $39.50 CAD/mo (50% off for 12 months)."),
        ("Public Launch (FOUNDING25):", "Publish 3+ consented beta testimonials on quotelytics.ca & LinkedIn; open FOUNDING25 (30% off -> $55.30/mo) for first 25 public customers."),
    ],
    accent_color=COLOR_RED_PRIMARY,
    body_size=10,
)

add_card(
    s13,
    Inches(6.8),
    Inches(1.75),
    Inches(5.733),
    Inches(2.45),
    "Phase 2: Scale Outbound & Unlock Milestone 1–2",
    [
        ("Hit Milestone 1 (5 Paid Accounts OR $5k ARR):", "Unlocks your first 250,000 Class B shares (~2.5%) + monthly 30% commission checks."),
        ("Upsell Broker Team ($199/mo):", "Move multi-dispatcher desks into 5-seat Team workspaces (~$59.70/mo commission per account)."),
    ],
    accent_color=COLOR_INDIGO,
    body_size=10,
)

add_card(
    s13,
    Inches(0.8),
    Inches(4.45),
    Inches(5.7),
    Inches(2.45),
    "Phase 3: Business Tier API Expansion (From $399/mo)",
    [
        ("Target 3PLs & ERPs:", "Use the Master Business Tier Formula ($399 base + degressive volume + seats + infra) to close high-ticket 3PLs."),
        ("3-Click IT Handoff:", "Use the Sales Onboarding Desk (/console/admin) to onboard Business accounts with zero coding."),
    ],
    accent_color=COLOR_EMERALD,
    body_size=10,
)

add_card(
    s13,
    Inches(6.8),
    Inches(4.45),
    Inches(5.733),
    Inches(2.45),
    "Year 1 Commercial North Star",
    [
        ("Target Milestone:", "50 paid brokerages (~$3,950+ CAD/mo | $47,400+ CAD/yr) by Month 12."),
        ("High-Margin Software:", "85%+ gross margins mean strong recurring commission & equity value."),
    ],
    accent_color=COLOR_SLATE_DARK,
    body_size=10,
)

set_notes(s13, "Beta is just the launchpad—the real recurring commissions and Class B equity milestones kick into high gear as we convert the beta cohort and scale public outreach.")


# =============================================================================
# SLIDE 17: IMMEDIATE ACTION ITEMS (TODAY)
# =============================================================================
s14 = prs.slides.add_slide(blank_layout)
apply_background(s14, COLOR_SLATE_DARK)

bar14 = s14.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.1))
bar14.fill.solid()
bar14.fill.fore_color.rgb = COLOR_RED_PRIMARY
bar14.line.fill.background()

t14 = s14.shapes.add_textbox(Inches(0.9), Inches(0.75), Inches(11.5), Inches(0.85))
p14 = t14.text_frame.paragraphs[0]
p14.text = "Let's Get Moving: 5 Quick Things to Do Right After This Call"
p14.font.size = Pt(27)
p14.font.bold = True
p14.font.color.rgb = COLOR_WHITE

actions = [
    ("1. Sign Independent Sales Rep Agreement (Doc 13)", "Review & sign 13_Independent_Sales_Rep_and_Milestone_Equity_Agreement.docx (30% comm + Class B milestones)."),
    ("2. Dylan Launches WHC Server & Files CBCA Incorporation", "Send WHC quote email (sales@whc.ca), deploy quotelytics.ca SSL, and file $200 Federal CBCA incorporation."),
    ("3. Run 3 Practice Quotes on /demo & Test /console/admin", "Practice the 5-step quote flow on /demo and preview the 3-click Business Tier API onboarding desk."),
    ("4. Claim Your Target Brokerages (Outside Quebec)", "Open Canadian_Freight_Brokerage_Target_Prospects.xlsx and split the non-Quebec brokerages to recruit 5 beta testers each."),
    ("5. Send Wave 1 Outreach & Sign Beta Agreements (Doc 11)", "Fire off Templates 01–03, book 15-min Zoom demos, and get your first 5 testers signed onto Doc 11!"),
]

y_pos = Inches(1.85)
for title, desc in actions:
    box = s14.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), y_pos, Inches(11.533), Inches(0.82)
    )
    box.fill.solid()
    box.fill.fore_color.rgb = COLOR_SLATE_NAVY
    box.line.color.rgb = COLOR_RED_PRIMARY
    box.line.width = Pt(1)

    tb = s14.shapes.add_textbox(Inches(1.15), y_pos + Inches(0.13), Inches(11.0), Inches(0.58))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    r1 = p.add_run()
    r1.text = title + " — "
    r1.font.size = Pt(13)
    r1.font.bold = True
    r1.font.color.rgb = RGBColor(252, 165, 165)

    r2 = p.add_run()
    r2.text = desc
    r2.font.size = Pt(11.5)
    r2.font.color.rgb = RGBColor(226, 232, 240)
    y_pos += Inches(0.98)

set_notes(s14, "Open the floor for questions, sign Document 13, and kick off our 10-broker beta recruitment!")

prs.save(OUTPUT_PATH)
print(f"Successfully generated {OUTPUT_PATH} ({len(prs.slides)} slides)")
