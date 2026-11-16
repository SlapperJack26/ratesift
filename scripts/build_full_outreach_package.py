"""Build the complete Quotelytics Outreach & Lead Generation Suite.
Outputs all files to the project 'outreach/' directory.
"""
import os
import csv
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

OUTREACH_DIR = os.path.abspath("outreach")

# -------------------------------------------------------------
# DOCX Helper Functions
# -------------------------------------------------------------
def set_cell_background(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=140, bottom=140, left=180, right=180):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def set_cell_border_left_accent(cell, hex_color="0F2942", sz="36"):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="none"/>'
        f'<w:left w:val="single" w:sz="{sz}" w:space="0" w:color="{hex_color}"/>'
        f'<w:bottom w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)

def set_cell_border_box(cell, hex_color="CBD5E1", sz="8"):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="{sz}" w:space="0" w:color="{hex_color}"/>'
        f'<w:left w:val="single" w:sz="{sz}" w:space="0" w:color="{hex_color}"/>'
        f'<w:bottom w:val="single" w:sz="{sz}" w:space="0" w:color="{hex_color}"/>'
        f'<w:right w:val="single" w:sz="{sz}" w:space="0" w:color="{hex_color}"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)

def format_doc_defaults(doc, doc_title="Quotelytics Outreach Kit"):
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)
        
        # Header
        hp = section.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run(f"QUOTELYTICS INC. • {doc_title.upper()}")
        hrun.font.name = "Calibri"
        hrun.font.size = Pt(8)
        hrun.font.color.rgb = RGBColor(148, 163, 184)
        
        # Footer
        fp = section.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        frun = fp.add_run("Quotelytics • https://quotelytics.ca • support@quotelytics.ca")
        frun.font.name = "Calibri"
        frun.font.size = Pt(8.5)
        frun.font.color.rgb = RGBColor(148, 163, 184)

    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)
    font.color.rgb = RGBColor(51, 65, 85)
    style.paragraph_format.line_spacing = 1.15
    style.paragraph_format.space_after = Pt(6)

def add_header_banner(doc, title, subtitle, category_tag="CASL B2B COLD EMAIL TEMPLATE"):
    p_tag = doc.add_paragraph()
    p_tag.paragraph_format.space_after = Pt(2)
    tag_run = p_tag.add_run(category_tag.upper())
    tag_run.font.name = "Calibri"
    tag_run.font.size = Pt(9)
    tag_run.font.bold = True
    tag_run.font.color.rgb = RGBColor(14, 116, 144)

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_after = Pt(3)
    t_run = p_title.add_run(title)
    t_run.font.name = "Calibri"
    t_run.font.size = Pt(19)
    t_run.font.bold = True
    t_run.font.color.rgb = RGBColor(15, 41, 66)

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(12)
    s_run = p_sub.add_run(subtitle)
    s_run.font.name = "Calibri"
    s_run.font.size = Pt(10.5)
    s_run.font.italic = True
    s_run.font.color.rgb = RGBColor(100, 116, 139)

    rule_table = doc.add_table(rows=1, cols=1)
    rule_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = rule_table.cell(0, 0)
    c.width = Inches(6.5)
    set_cell_background(c, "E2E8F0")
    h = parse_xml(f'<w:trHeight {nsdecls("w")} w:val="20" w:hRule="exact"/>')
    rule_table.rows[0]._tr.get_or_add_trPr().append(h)
    
    doc.add_paragraph().paragraph_format.space_after = Pt(8)

def add_callout(doc, title, content_lines, hex_bg="F8FAFC", border_color="0F2942"):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, hex_bg)
    set_cell_margins(cell, top=140, bottom=140, left=180, right=180)
    set_cell_border_left_accent(cell, hex_color=border_color, sz="36")
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(4)
    t_run = p.add_run(f"📌  {title.upper()}")
    t_run.font.bold = True
    t_run.font.size = Pt(9.5)
    t_run.font.color.rgb = RGBColor(15, 41, 66)
    
    for idx, line in enumerate(content_lines):
        cp = cell.add_paragraph()
        cp.paragraph_format.space_after = Pt(3 if idx < len(content_lines)-1 else 0)
        crun = cp.add_run(line)
        crun.font.size = Pt(9.5)
        crun.font.color.rgb = RGBColor(51, 65, 85)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

def add_subject_box(doc, subject_text, label="EMAIL SUBJECT LINE:"):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, "EFF6FF")
    set_cell_margins(cell, top=130, bottom=130, left=160, right=160)
    set_cell_border_box(cell, hex_color="BFDBFE", sz="10")

    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    lbl = p.add_run(f"{label}  ")
    lbl.font.bold = True
    lbl.font.size = Pt(10)
    lbl.font.color.rgb = RGBColor(29, 78, 216)
    
    val = p.add_run(subject_text)
    val.font.bold = True
    val.font.size = Pt(10.5)
    val.font.color.rgb = RGBColor(15, 23, 42)

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

def add_casl_footer_box(doc):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, "F1F5F9")
    set_cell_margins(cell, top=130, bottom=130, left=160, right=160)
    set_cell_border_box(cell, hex_color="CBD5E1", sz="8")

    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    hdr = p.add_run("⚖️  MANDATORY CASL STATUTORY EMAIL FOOTER (S.C. 2010, c. 23)")
    hdr.font.bold = True
    hdr.font.size = Pt(8.5)
    hdr.font.color.rgb = RGBColor(71, 85, 105)

    lines = [
        "Quotelytics Inc. • [INSERT PHYSICAL BUSINESS ADDRESS, CITY, ON, POSTAL CODE] • Canada",
        "You received this message because your business contact information is publicly published in connection with logistics management at {{company_name}} (CASL s. 10(9)(b)).",
        "If you do not wish to receive commercial updates from Quotelytics, you may Unsubscribe Instantly: https://quotelytics.ca/unsubscribe?email={{email}}"
    ]
    for line in lines:
        lp = cell.add_paragraph()
        lp.paragraph_format.space_after = Pt(2)
        r = lp.add_run(line)
        r.font.size = Pt(8.5)
        r.font.italic = True
        r.font.color.rgb = RGBColor(100, 116, 139)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

def add_h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    r.font.name = "Calibri"
    r.font.size = Pt(13)
    r.font.bold = True
    r.font.color.rgb = RGBColor(15, 41, 66)

def add_h3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(text)
    r.font.name = "Calibri"
    r.font.size = Pt(11.5)
    r.font.bold = True
    r.font.color.rgb = RGBColor(30, 58, 138)

def add_quote_block(doc, quote_text):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, "F8FAFC")
    set_cell_margins(cell, top=120, bottom=120, left=160, right=160)
    set_cell_border_left_accent(cell, hex_color="0284C7", sz="24")
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(quote_text)
    r.font.italic = True
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor(30, 41, 59)
    
    doc.add_paragraph().paragraph_format.space_after = Pt(6)


# -------------------------------------------------------------
# Base Documents (00 to 07)
# -------------------------------------------------------------
def build_doc_00():
    doc = Document()
    format_doc_defaults(doc, "Outreach Campaign Master Playbook")
    add_header_banner(
        doc,
        "Quotelytics Outreach Campaign Master Playbook",
        "Comprehensive execution manual: CASL compliance, email sending cadences, LinkedIn strategies, and response workflows.",
        "GO-TO-MARKET EXECUTION MANUAL"
    )
    add_callout(doc, "Campaign Overview & Architecture", [
        "Purpose: Serve as the single reference manual for all direct founder outreach across Canada.",
        "Folder Contents: Complete suite of specialized Microsoft Word (.docx) documents tailored for email, LinkedIn, onboarding, and lead tracking.",
        "Governing Legal Framework: Canada's Anti-Spam Legislation (CASL, S.C. 2010, c. 23) and PIPEDA.",
        "Target Launch Metric: 10 Canadian freight brokerages onboarded to private beta; 5 conversions to founding paid tier."
    ])

    add_h2(doc, "1. Directory Manifest of Outreach Documents")
    
    docs_info = [
        ("01_Email_Brokerage_Owners_and_Ops_Directors.docx", "Executive cold email targeting owners & VPs of operations. Emphasizes dispatch labor hours, manual bottleneck elimination, and 100% Canadian data residency."),
        ("02_Email_Dispatch_Managers_and_Lead_Brokers.docx", "Dispatcher-focused cold email highlighting CWT weight breaks, deficit thresholds, and the zero-signup browser demo (https://quotelytics.ca/demo)."),
        ("03_Email_Freight_Forwarders_and_3PL_Account_Executives.docx", "Sales-focused cold email highlighting 1-click client proposal PDFs, markup sliders, and shipper-ready quotes."),
        ("04_LinkedIn_Announcement_Founder_Story.docx", "Founder story post detailing why Canadian freight rating is broken and inviting 10 beta testers."),
        ("05_LinkedIn_Educational_Deficit_Rating_Math.docx", "Technical authority post breaking down the $26.25 deficit rating math trap and how deficit rating works."),
        ("06_LinkedIn_Founding_Customer_Offer.docx", "Commercial conversion post offering the FOUNDING25 promo code for 30% off Broker Pro ($55 CAD/mo)."),
        ("07_Private_Beta_Onboarding_Script_and_Interview.docx", "15-minute live screen-share walkthrough script, discovery questions, and testimonial capture prompt."),
        ("08_Drip_Email_Day_0_Welcome_and_Tariff_Calibration.docx", "Immediate post-signup email offering white-glove tariff ingestion within 4 hours."),
        ("09_Drip_Email_Day_3_Deficit_Rating_Tip.docx", "Educational engagement email showing dispatchers how deficit rating saves $20-$50 per load."),
        ("10_Drip_Email_Day_7_Proposal_PDF_Walkthrough.docx", "Value demonstration email teaching brokers how to generate 1-click branded Client Proposals."),
        ("Canadian_Freight_Brokerage_Target_Prospects.xlsx", "CRM workbook with target Canadian brokerages across ON, QC, and Western Canada.")
    ]
    
    for filename, desc in docs_info:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(filename + ": ").bold = True
        p.add_run(desc)

    add_h2(doc, "2. CASL Compliance Protocol for Canadian Cold Outreach")
    doc.add_paragraph("Canada has strict anti-spam laws (CASL, S.C. 2010, c. 23). To ensure 100% compliance during B2B outreach:")
    
    casl_points = [
        ("Conspicuously Published Email Address (CASL § 10(9)(b)): ", "You may only email a Canadian business recipient without express consent if their email address is conspicuously published on their company website, public directory, or LinkedIn, AND there is no statement refusing unsolicited commercial messages."),
        ("Direct Role Relevance: ", "The message MUST be directly relevant to the recipient's business role, function, or duties (e.g. freight dispatching, logistics operations, brokerage ownership)."),
        ("Sender Identification: ", "Every email must clearly state Quotelytics Inc., physical mailing address, and contact info (support@quotelytics.ca / 289-929-8565)."),
        ("1-Click Unsubscribe Mechanism: ", "Every email must contain a functional 1-click unsubscribe URL (https://quotelytics.ca/unsubscribe?email=...) that immediately records the opt-out.")
    ]
    for title, desc in casl_points:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(title).bold = True
        p.add_run(desc)

    add_h2(doc, "3. Weekly Sending & Publishing Schedule")
    
    tbl = doc.add_table(rows=6, cols=3)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["Day & Time", "Channel & Template", "Target Outcome"]
    for i, h in enumerate(headers):
        c = tbl.cell(0, i)
        set_cell_background(c, "0F2942")
        p = c.paragraphs[0]
        r = p.add_run(h)
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)
        set_cell_margins(c, 100, 100, 120, 120)

    rows_data = [
        ("Tuesday 8:30 AM", "Template 1 (Owners / Ops Directors)", "Book 1-2 onboarding calls for Thursday"),
        ("Tuesday 8:00 AM", "LinkedIn Post 1 (Founder Announcement)", "Generate viral impressions, likes, and inbound DMs"),
        ("Wednesday 9:00 AM", "Template 2 (Dispatch Managers)", "Drive dispatchers to test https://quotelytics.ca/demo"),
        ("Thursday 8:30 AM", "LinkedIn Post 2 (Deficit Rating Math)", "Establish technical domain authority & comments"),
        ("Thursday 2:00 PM", "Template 3 (Freight Forwarders)", "Schedule 1-click proposal demo for following week")
    ]
    for row_idx, r_data in enumerate(rows_data):
        for col_idx, text in enumerate(r_data):
            c = tbl.cell(row_idx+1, col_idx)
            set_cell_background(c, "FFFFFF" if row_idx % 2 == 0 else "F8FAFC")
            set_cell_border_box(c, "E2E8F0", sz="4")
            set_cell_margins(c, 80, 80, 100, 100)
            p = c.paragraphs[0]
            r = p.add_run(text)
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(51, 65, 85)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)
    
    add_h2(doc, "4. Follow-Up Protocol")
    doc.add_paragraph("Follow up strictly once, 3 to 4 business days after the initial email if no reply:")
    add_quote_block(
        doc,
        '"Hi {{first_name}},\n\nWanted to quickly bump this in case it got buried in dispatch emails. Did you get a chance to see how Quotelytics turns carrier Excel rate sheets into instant 500ms quotes?\n\nHappy to run a quick 5-minute comparison if you have a minute tomorrow.\n\nBest, Dylan"'
    )

    path = os.path.join(OUTREACH_DIR, "00_Outreach_Campaign_Master_Playbook.docx")
    doc.save(path)
    return path

def build_doc_01():
    doc = Document()
    format_doc_defaults(doc, "Template 1: Brokerage Owners & Ops Directors")
    add_header_banner(
        doc,
        "Template 1: For Brokerage Owners & Operations Directors",
        "Direct cold outreach targeting executive leadership at Canadian freight brokerages.",
        "CASL B2B COLD EMAIL TEMPLATE"
    )
    add_callout(doc, "Campaign Specifications", [
        "Target Audience: Owner, President, Managing Director, VP of Operations at small/mid-size Canadian 3PLs (1–20 dispatchers).",
        "Legal Basis: Canada's Anti-Spam Legislation (CASL, S.C. 2010, c. 23) § 10(9)(b) Conspicuously Published Business Email Exception.",
        "Value Proposition: Eliminating 15 minutes of manual CWT spreadsheet calculations per quote; 100% data sovereignty.",
        "Call to Action: 10-minute demo this Thursday or Friday on one of their own carrier spreadsheets."
    ])
    add_subject_box(doc, "Question regarding manual tariff quoting at {{company_name}} / Instant CWT rating")

    add_h2(doc, "Email Body Copy")
    doc.add_paragraph("Hi {{first_name}},")
    doc.add_paragraph("I noticed {{company_name}} manages LTL and freight dispatch across Ontario and Western Canada.")
    doc.add_paragraph(
        "If your dispatchers are like most Canadian brokerages, they spend 10 to 20 minutes on every quote cross-referencing multi-tab Excel rate matrices from carriers like Day & Ross, Manitoulin, or Midland—often calculating CWT breaks and deficit thresholds by hand."
    )
    p = doc.add_paragraph()
    p.add_run("We built ")
    p.add_run("Quotelytics").bold = True
    p.add_run(" (https://quotelytics.ca) specifically to eliminate that manual bottleneck.")
    
    doc.add_paragraph(
        "You upload your negotiated carrier Excel spreadsheets once. When a shipper calls for a quote, you input the origin and destination postal codes (e.g. M5V 2T6 → T2P 1J9), and Quotelytics ranks every carrier in under 500ms, itemizing base rates, fuel surcharges, and deficit breaks with 100% mathematical precision."
    )
    
    doc.add_paragraph("Most importantly:")
    bp1 = doc.add_paragraph(style='List Bullet')
    bp1.add_run("Zero Carrier Lock-in: ").bold = True
    bp1.add_run("We don’t book trucks or take commission—pure deterministic rating intelligence.")
    
    bp2 = doc.add_paragraph(style='List Bullet')
    bp2.add_run("100% Canadian Data Sovereignty: ").bold = True
    bp2.add_run("All rate cards are strictly tenant-isolated and stored in Montreal and Halifax under PIPEDA.")
    
    doc.add_paragraph("We are offering 10 Canadian freight brokerages free onboarding and tariff calibration this month during our private beta.")
    doc.add_paragraph("Would you be open to a 10-minute demo this Thursday or Friday to see how it works on one of your own spreadsheets?")
    doc.add_paragraph("Best regards,")
    
    psig = doc.add_paragraph()
    psig.add_run("Dylan\n").bold = True
    psig.add_run("Founder & Product Engineer | Quotelytics Inc.\n")
    psig.add_run("support@quotelytics.ca • Direct: 289-929-8565\n")
    psig.add_run("https://quotelytics.ca")

    add_casl_footer_box(doc)
    
    path = os.path.join(OUTREACH_DIR, "01_Email_Brokerage_Owners_and_Ops_Directors.docx")
    doc.save(path)
    return path

def build_doc_02():
    doc = Document()
    format_doc_defaults(doc, "Template 2: Dispatch Managers & Lead Brokers")
    add_header_banner(
        doc,
        "Template 2: For Dispatch Managers & Lead Brokers",
        "Operational cold outreach targeting daily freight dispatchers and logistics coordinators.",
        "CASL B2B COLD EMAIL TEMPLATE"
    )
    add_callout(doc, "Campaign Specifications", [
        "Target Audience: Dispatch Manager, Lead Freight Broker, Logistics Coordinator, Senior Dispatcher.",
        "Tone & Angle: Ground-level dispatcher empathy; eliminating spreadsheet scramble and desk calculator errors.",
        "Key Feature Highlighted: Live browser demo link (https://quotelytics.ca/demo) requiring zero signup.",
        "Follow-Up Cadence: Day 0 (initial send) -> Day 3 (quick polite ping) -> Day 7 (final value drop)."
    ])
    add_subject_box(doc, "Instant multi-carrier quote comparisons from your spreadsheets")

    add_h2(doc, "Email Body Copy")
    doc.add_paragraph("Hi {{first_name}},")
    doc.add_paragraph(
        "As the dispatch lead at {{company_name}}, how much time does your team spend flipping between different carrier Excel tariffs to quote a 4-skid LTL shipment?"
    )
    doc.add_paragraph("When a customer needs an urgent quote, manually calculating:")
    
    b1 = doc.add_paragraph(style='List Bullet')
    b1.add_run("CWT weight break brackets (L5C, M5C, M1M, M2M)")
    b2 = doc.add_paragraph(style='List Bullet')
    b2.add_run("Deficit rating thresholds (whether 850 lbs is cheaper rated at 1,000 lbs)")
    b3 = doc.add_paragraph(style='List Bullet')
    b3.add_run("Weekly fluctuating diesel fuel surcharge indices")

    doc.add_paragraph("...can turn a simple quote request into a 15-minute spreadsheet scramble.")
    
    p = doc.add_paragraph()
    p.add_run("We developed ")
    p.add_run("Quotelytics").bold = True
    p.add_run(" (https://quotelytics.ca) to automate that entire workflow directly from your existing Excel files (.xlsx, .csv). You get side-by-side carrier price rankings in seconds, with every dollar traced back to the exact cell in your original spreadsheet.")

    doc.add_paragraph("You can test drive the engine right in your browser with synthetic Canadian data (no signup required):")
    p_demo = doc.add_paragraph()
    p_demo.paragraph_format.left_indent = Inches(0.25)
    r_demo = p_demo.add_run("👉 https://quotelytics.ca/demo")
    r_demo.bold = True
    r_demo.font.color.rgb = RGBColor(14, 116, 144)

    doc.add_paragraph(
        "If you'd like to test it on one of your real carrier rate cards, I'd be happy to set up a complimentary beta account for your dispatch desk."
    )
    doc.add_paragraph("Would you have 5 minutes this week for a quick chat?")
    doc.add_paragraph("Thanks,")

    psig = doc.add_paragraph()
    psig.add_run("Dylan\n").bold = True
    psig.add_run("Quotelytics Inc. • support@quotelytics.ca • 289-929-8565\n")
    psig.add_run("https://quotelytics.ca")

    add_casl_footer_box(doc)
    
    path = os.path.join(OUTREACH_DIR, "02_Email_Dispatch_Managers_and_Lead_Brokers.docx")
    doc.save(path)
    return path

def build_doc_03():
    doc = Document()
    format_doc_defaults(doc, "Template 3: Freight Forwarders & 3PL Account Execs")
    add_header_banner(
        doc,
        "Template 3: For Freight Forwarders & 3PL Account Executives",
        "Sales-oriented cold outreach highlighting customer markup toggles and instant branded PDF rate proposals.",
        "CASL B2B COLD EMAIL TEMPLATE"
    )
    add_callout(doc, "Campaign Specifications", [
        "Target Audience: Freight Forwarder Account Executive, 3PL Account Manager, Commercial Logistics Pricing Specialist.",
        "Value Proposition: Eliminating manual copy-pasting into client emails; generating branded Client Rate Proposal PDFs in 1-click.",
        "Security & Compliance: 100% Canadian data residency (WHC Montreal/Halifax) and tenant isolation under PIPEDA.",
        "Call to Action: Brief 10-minute walk-through next Tuesday at 2:00 PM EST."
    ])
    add_subject_box(doc, "1-click branded customer rate proposals from your Excel tariffs")

    add_h2(doc, "Email Body Copy")
    doc.add_paragraph("Hi {{first_name}},")
    doc.add_paragraph("Quick question: when a corporate shipper asks for an LTL quote, how does your pricing team format the final proposal?")
    doc.add_paragraph(
        "At Quotelytics, we noticed freight forwarders and 3PL account executives were spending valuable hours manually retyping numbers from carrier Excel matrices into PDFs or emails."
    )
    
    p = doc.add_paragraph()
    p.add_run("Quotelytics").bold = True
    p.add_run(" (https://quotelytics.ca) allows forwarders to:")
    
    b1 = doc.add_paragraph(style='List Bullet')
    b1.add_run("Ingest carrier spreadsheets ").bold = True
    b1.add_run("and instantly rank carriers by lowest billable cost.")
    
    b2 = doc.add_paragraph(style='List Bullet')
    b2.add_run("Apply brokerage markups ").bold = True
    b2.add_run("(flat dollar or margin percentage) with one toggle.")
    
    b3 = doc.add_paragraph(style='List Bullet')
    b3.add_run("Generate a clean, branded Client Rate Proposal PDF ").bold = True
    b3.add_run("in one click, ready to send directly to your customer.")

    doc.add_paragraph(
        "Our engine is deterministic, runs at 0ms latency, and keeps all commercial data sovereign on Canadian servers (WHC Montreal/Halifax)."
    )
    doc.add_paragraph("Are you free for a brief 10-minute walk-through next Tuesday at 2:00 PM EST?")
    doc.add_paragraph("Best,")

    psig = doc.add_paragraph()
    psig.add_run("Dylan\n").bold = True
    psig.add_run("Quotelytics Inc. • support@quotelytics.ca • 289-929-8565\n")
    psig.add_run("https://quotelytics.ca")

    add_casl_footer_box(doc)
    
    path = os.path.join(OUTREACH_DIR, "03_Email_Freight_Forwarders_and_3PL_Account_Executives.docx")
    doc.save(path)
    return path

def build_doc_04():
    doc = Document()
    format_doc_defaults(doc, "LinkedIn Post 1: Founder Announcement")
    add_header_banner(
        doc,
        "Post 1: The Announcement & Founder Story",
        "Public launch and storytelling post designed to generate initial viral reach, comments, and private beta inbound requests.",
        "LINKEDIN & SOCIAL CONTENT PLAYBOOK"
    )
    add_callout(doc, "Post Strategy & Publishing Guide", [
        "Goal: Introduce Quotelytics, articulate the painful manual freight quoting problem, and invite Canadian brokers to test drive.",
        "Primary Channels: Founder Personal LinkedIn Profile, Freight Broker Groups, r/FreightBrokers.",
        "Timing: Launch Day (Tuesday or Wednesday at 8:00 AM EST).",
        "Formatting Best Practice: Leave single blank line between paragraphs; avoid external link in the post body (put in first comment if algorithm penalizes external links)."
    ])
    add_subject_box(doc, "Why Canadian Freight Brokers Waste 25 Minutes on Every LTL Quote", "POST TOPIC / HOOK:")

    add_h2(doc, "LinkedIn Copy (Ready to Copy & Paste)")

    lines = [
        "Canadian freight brokers waste 10 to 25 minutes on *every single LTL quote*.",
        "",
        "Here’s why:",
        "A customer asks for a quote from Toronto (M5V) to Montreal (H3B) on 4 skids weighing 4,200 lbs.",
        "What does the dispatcher have to do?",
        "1. Open Excel sheet #1 (Carrier A). Cross-reference the FSA matrix. Look up the M2M CWT break. Calculate fuel.",
        "2. Open Excel sheet #2 (Carrier B). Check if there's a deficit rating threshold.",
        "3. Open Excel sheet #3 (Carrier C). Check if tailgate or appointment accessorials apply.",
        "4. Calculate everything by hand on a desk calculator.",
        "5. Re-type it into an email or client quote.",
        "",
        "Do that 15 times a day, and half your week is eaten by spreadsheet cross-referencing. Worse: if you miss a deficit break, you overcharge your customer or eat the margin yourself.",
        "",
        "I got tired of watching logistics teams deal with this clunky workflow.",
        "",
        "So we built Quotelytics (https://quotelytics.ca) — a deterministic Canadian freight rating engine.",
        "",
        "Here is how it works:",
        "1. Drag and drop your existing carrier Excel tariffs (.xlsx, .csv).",
        "2. Type in the origin and destination postal codes (e.g. M5V 2T6 → H3B 2Y5) and weight.",
        "3. In under 500 milliseconds, every carrier tariff in your account is ranked from lowest to highest billable cost.",
        "4. Every single calculation is completely deterministic and traces back to the exact cell in your original Excel sheet.",
        "",
        "We don’t book trucks, we don’t print labels, and we don’t share your confidential rates with anyone (100% Canadian data residency in Montreal & Halifax).",
        "",
        "We are opening 10 free beta spots for Canadian freight brokerages and 3PLs this month.",
        "",
        "If you want to quote in seconds instead of minutes, drop a comment or DM me, and I’ll get your account set up today.",
        "",
        "#FreightBrokers #CanadianLogistics #FreightTech #SupplyChainCanada #LTLFreight #3PL"
    ]
    for line in lines:
        if line == "":
            doc.add_paragraph().paragraph_format.space_after = Pt(4)
        elif line.startswith("#"):
            p = doc.add_paragraph()
            r = p.add_run(line)
            r.font.bold = True
            r.font.color.rgb = RGBColor(14, 116, 144)
        else:
            doc.add_paragraph(line)

    add_callout(doc, "Engagement Action Items", [
        "Pin the live interactive demo link in the first comment: 'Test drive the engine with synthetic Canadian tariffs: https://quotelytics.ca/demo'",
        "Respond to all comments within 15 minutes of posting to maximize LinkedIn algorithm velocity.",
        "Direct-message everyone who likes or comments with an invitation to the 10-minute onboarding screen-share."
    ], hex_bg="FEF3C7", border_color="D97706")

    path = os.path.join(OUTREACH_DIR, "04_LinkedIn_Announcement_Founder_Story.docx")
    doc.save(path)
    return path

def build_doc_05():
    doc = Document()
    format_doc_defaults(doc, "LinkedIn Post 2: Deficit Rating Math")
    add_header_banner(
        doc,
        "Post 2: The Deficit Rating Math Trap",
        "Thought-leadership and technical authority post demonstrating exact mathematical competence in Canadian LTL tariff structures.",
        "LINKEDIN & SOCIAL CONTENT PLAYBOOK"
    )
    add_callout(doc, "Post Strategy & Publishing Guide", [
        "Goal: Establish undeniable domain authority by exposing a common $26.25 manual rating error in Canadian freight.",
        "Audience Reaction: Dispatch managers and owners will recognize the exact problem and question their desk's calculations.",
        "Format: Educational quiz format followed by clean mathematical breakdown.",
        "Timing: Week 2 (Thursday morning at 8:30 AM EST)."
    ])
    add_subject_box(doc, "Canadian Freight Math Quiz: The $26.25 Deficit Rating Mistake", "POST TOPIC / HOOK:")

    add_h2(doc, "LinkedIn Copy (Ready to Copy & Paste)")

    lines = [
        "Quick freight math quiz for Canadian LTL brokers:",
        "",
        "Shipment: Toronto (M5V) → Calgary (T2P)",
        "Weight: 850 lbs",
        "Tariff Rates:",
        "- Base rate (500 lbs break): $24.50 / CWT",
        "- Next break rate (1,000 lbs break): $18.20 / CWT",
        "",
        "How much should this shipment bill?",
        "",
        "Option A: (850 lbs / 100) × $24.50 = $208.25",
        "Option B: (1,000 lbs / 100) × $18.20 = $182.00",
        "",
        "If your dispatcher bills Option A, they just cost your shipper an unnecessary $26.25 overcharge.",
        "",
        "This is Deficit Rating, a standard rule in Canadian LTL tariffs. When a shipment approaches the next discount bracket, carrier tariffs allow rating as if the shipment weighed the minimum of the next bracket if the resulting charge is lower.",
        "",
        "Doing this by hand across 12 different carrier Excel sheets is where human errors explode:",
        "• Some carriers have deficit breaks at 500, 1M, and 2M.",
        "• Others have flat minimum floors that supersede deficit breaks.",
        "• And fuel surcharges apply after the deficit calculation, not before.",
        "",
        "At Quotelytics (https://quotelytics.ca), we engineered a deterministic calculation engine that tests both actual weight and deficit thresholds in 0.02ms for every single lane.",
        "",
        "Never miss a discount break again.",
        "",
        "Brokers: How does your team handle deficit calculations today? Mental math or spreadsheet macros?",
        "",
        "#LogisticsManagement #FreightBrokers #LTLTariffs #Quotelytics #SupplyChain"
    ]
    for line in lines:
        if line == "":
            doc.add_paragraph().paragraph_format.space_after = Pt(4)
        elif line.startswith("#"):
            p = doc.add_paragraph()
            r = p.add_run(line)
            r.font.bold = True
            r.font.color.rgb = RGBColor(14, 116, 144)
        else:
            doc.add_paragraph(line)

    add_callout(doc, "Discussion Prompt Strategy", [
        "Tag 2-3 friendly freight brokers or dispatchers in the comments asking for their takes.",
        "When commenters reply with 'Option B', praise their accuracy and ask how long it takes their team to verify that across 5 carriers."
    ], hex_bg="F0FDF4", border_color="16A34A")

    path = os.path.join(OUTREACH_DIR, "05_LinkedIn_Educational_Deficit_Rating_Math.docx")
    doc.save(path)
    return path

def build_doc_06():
    doc = Document()
    format_doc_defaults(doc, "LinkedIn Post 3: Founding Customer Offer")
    add_header_banner(
        doc,
        "Post 3: The Founding Customer Program Offer",
        "Conversion and commercial offer post introducing the limited 25-spot discount coupon code.",
        "LINKEDIN & SOCIAL CONTENT PLAYBOOK"
    )
    add_callout(doc, "Offer Details & Mechanics", [
        "Goal: Convert early beta users and social followers into paid recurring Broker Pro subscribers.",
        "Promo Code: FOUNDING25 (Configured in Stripe for 30% lifetime/1-year recurring discount).",
        "Founding Price: $55 CAD/month (Standard price: $79 CAD/month).",
        "High-Touch Incentive: Free manual calibration of their first 5 carrier Excel tariffs by our engineering desk."
    ])
    add_subject_box(doc, "Official Launch: Quotelytics Founding Customer Program (30% Off)", "POST TOPIC / HOOK:")

    add_h2(doc, "LinkedIn Copy (Ready to Copy & Paste)")

    lines = [
        "To the first 25 Canadian freight brokerages joining Quotelytics:",
        "",
        "We are officially launching our Founding Customer Program today.",
        "",
        "If you run a Canadian brokerage or 3PL with 1 to 15 dispatchers, you know the frustration of quoting multi-carrier LTL from raw spreadsheets.",
        "",
        "Starting today, you can lock in:",
        "✅ 30% OFF Broker Pro for your entire first year ($55 CAD/mo instead of $79 CAD/mo)",
        "✅ Ingestion and calibration of your first 5 carrier Excel tariffs handled by our dispatch engineering desk",
        "✅ Direct access to our private WhatsApp/phone dispatch hotline (289-929-8565)",
        "✅ Unlimited quote traceability back to original spreadsheet cells",
        "✅ 100% Canadian data residency (WHC Montreal & Halifax)",
        "",
        "No booking lock-in. No AI hallucinations. Just instant, deterministic freight rates verified to the penny.",
        "",
        "Only 25 founding coupons available: use code FOUNDING25 at checkout.",
        "",
        "Test drive it free right now: https://quotelytics.ca/demo",
        "",
        "#CanadianLogistics #FreightBroker #SaaS #FreightRating #LogisticsTechnology"
    ]
    for line in lines:
        if line == "":
            doc.add_paragraph().paragraph_format.space_after = Pt(4)
        elif line.startswith("#"):
            p = doc.add_paragraph()
            r = p.add_run(line)
            r.font.bold = True
            r.font.color.rgb = RGBColor(14, 116, 144)
        else:
            doc.add_paragraph(line)

    add_callout(doc, "Conversion Protocol", [
        "Monitor Stripe dashboard for activations.",
        "Send personal welcome email immediately upon checkout offering to ingest their Excel files within 4 hours.",
        "Provide emergency support hotline: 289-929-8565."
    ], hex_bg="FEF2F2", border_color="DC2626")

    path = os.path.join(OUTREACH_DIR, "06_LinkedIn_Founding_Customer_Offer.docx")
    doc.save(path)
    return path

def build_doc_07():
    doc = Document()
    format_doc_defaults(doc, "Beta Onboarding Script & Playbook")
    add_header_banner(
        doc,
        "Private Beta Tester Onboarding & Discovery Script",
        "Complete 15-minute live screen-share walkthrough script, discovery questions, and testimonial capture prompts.",
        "SALES & CUSTOMER ONBOARDING PLAYBOOK"
    )
    add_callout(doc, "Session Objectives & Rules of Engagement", [
        "Time Box: Strictly 15 minutes. Respect the broker's busy dispatch desk schedule.",
        "Primary Goal: Get 1 real carrier Excel tariff ingested and produce 1 verified quote that matches their manual calculation.",
        "Secondary Goal: Capture qualitative feedback on speed, deficit accuracy, and pre-sell the $79 CAD/mo Pro tier."
    ])

    add_h2(doc, "1. Pre-Call Preparation Checklist")
    doc.add_paragraph("Before hopping on the phone or Zoom / Teams screen-share with a beta broker:")
    
    b1 = doc.add_paragraph(style='List Bullet')
    b1.add_run("Verify Account Provisioning: ").bold = True
    b1.add_run("Ensure the broker's account is provisioned or have their signup link ready (https://quotelytics.ca/get-started).")
    
    b2 = doc.add_paragraph(style='List Bullet')
    b2.add_run("Gather Real Carrier Tariff: ").bold = True
    b2.add_run("Confirm the broker has 1 real carrier Excel tariff (.xlsx or .csv) ready on their desktop (e.g. Day & Ross, Manitoulin, Midland, Maritime-Ontario, or Bison).")
    
    b3 = doc.add_paragraph(style='List Bullet')
    b3.add_run("Have Demo Fallback Ready: ").bold = True
    b3.add_run("Open https://quotelytics.ca/demo in a background tab in case their corporate IT restricts uploading.")

    add_h2(doc, "2. The 15-Minute Live Onboarding Script")

    add_h3(doc, "Phase 1: Context & Problem Alignment (Minutes 0–3)")
    add_quote_block(
        doc,
        '"Thanks for taking the time, {{name}}. As you know, we built Quotelytics because Canadian dispatchers are spending hours every week manually calculating CWT breaks, deficit thresholds, and fuel surcharges across multiple spreadsheets.\n\nOur goal today is simple: take one of your real carrier rate sheets, upload it, and produce an instant ranked quote in under 60 seconds so you can see if the math matches what you calculate by hand."'
    )

    add_h3(doc, "Phase 2: Live Sheet Upload & Human Confirmation Gate (Minutes 3–7)")
    doc.add_paragraph("1. Screen-share: Guide the broker to https://quotelytics.ca/console/rate-sheets")
    doc.add_paragraph("2. Drag & Drop: Have them drag their Excel file into the upload dropzone.")
    doc.add_paragraph("3. The Confirmation Gate:")
    add_quote_block(
        doc,
        '"Notice how the system auto-detects your columns: Origin FSA, Destination FSA, Min Floor, and weight breaks (L5C, M5C, M1M, etc.). You can inspect the cell coordinates right here before confirming."'
    )
    doc.add_paragraph("4. Click \'Confirm & Ingest\'.")

    add_h3(doc, "Phase 3: Quoting & Mathematical Verification (Minutes 7–11)")
    doc.add_paragraph("1. Navigate to New Quote (/console/new-quote).")
    doc.add_paragraph("2. Have the broker input a lane they quote frequently:")
    bp_lane1 = doc.add_paragraph(style='List Bullet')
    bp_lane1.add_run("Origin: e.g. M5V 2T6 or TORONTO, ON")
    bp_lane2 = doc.add_paragraph(style='List Bullet')
    bp_lane2.add_run("Destination: e.g. T2P 1J9 or CALGARY, AB")
    bp_lane3 = doc.add_paragraph(style='List Bullet')
    bp_lane3.add_run("Weight: e.g. 1,850 lbs")
    
    doc.add_paragraph("3. Click \'Calculate Rates\'.")
    doc.add_paragraph("4. Inspect Results:")
    add_quote_block(
        doc,
        '"Here are all your eligible carriers ranked lowest to highest. Notice how it itemizes base rate, fuel surcharge, and net quote."'
    )
    doc.add_paragraph("5. Open Audit Drawer:")
    add_quote_block(
        doc,
        '"Click on the quote. Look at this: \'Sheet 1 • Row 18, Column D\'. Every dollar is mathematically mapped back to the exact cell in your original spreadsheet. No AI hallucinations, no guesses."'
    )
    doc.add_paragraph("6. Demonstrate 1-Click Client Proposal:")
    add_quote_block(
        doc,
        '"Toggle on a 15% brokerage markup, click \'Export Client Proposal PDF\', and you have a polished quote sheet ready to send to your shipper."'
    )

    add_h2(doc, "3. Feedback Discovery Questions (Minutes 11–15)")
    doc.add_paragraph("Ask these exact questions and record their verbatim responses:")

    q1 = doc.add_paragraph(style='List Bullet')
    q1.add_run("On Accuracy & Math: ").bold = True
    q1.add_run('"Does this rate match what you or your dispatchers would have calculated by hand for this lane? Did the deficit rating break at the threshold you expected?"')

    q2 = doc.add_paragraph(style='List Bullet')
    q2.add_run("On Tariff Formats: ").bold = True
    q2.add_run('"Are there any complex accessorials or footnote rules in your other tariffs (like beyond charges or tailgate rules) that we should test next?"')

    q3 = doc.add_paragraph(style='List Bullet')
    q3.add_run("On Workflow & Time Savings: ").bold = True
    q3.add_run('"If your team had this for all 5–10 of your primary carriers, how much time would this save your desk each day?"')

    q4 = doc.add_paragraph(style='List Bullet')
    q4.add_run("On Pricing & Value (Pre-Selling the $79 Pro Tier): ").bold = True
    q4.add_run('"When we launch paid accounts on December 1st at $79 CAD/month, would this be an easy return on investment for your brokerage?"')

    add_h2(doc, "4. Testimonial Capture Script")
    doc.add_paragraph("If the broker expresses enthusiasm during the session, immediately ask:")
    add_quote_block(
        doc,
        '"{{Name}}, that means a lot. Would you mind if I quoted you on that for our website? Something like: \'[Quote about saving 15 minutes per quote]\' — {{Name}}, Operations Manager at {{Company}}?"'
    )
    doc.add_paragraph("Record the testimonial in marketing/TESTIMONIALS_BETA.md for launch day!")

    path = os.path.join(OUTREACH_DIR, "07_Private_Beta_Onboarding_Script_and_Interview.docx")
    doc.save(path)
    return path


# -------------------------------------------------------------
# Onboarding Drip Sequence (08 to 10)
# -------------------------------------------------------------
def build_doc_08():
    doc = Document()
    format_doc_defaults(doc, "Onboarding Drip: Day 0 Welcome & Calibration")
    add_header_banner(
        doc,
        "Drip Email 1 (Day 0): Welcome & Free Tariff Ingestion",
        "Sent automatically immediately upon account registration (or manual invite activation).",
        "AUTOMATED ONBOARDING DRIP SEQUENCE"
    )
    add_callout(doc, "Trigger & Objectives", [
        "Trigger: User completes registration at https://quotelytics.ca/get-started.",
        "Timing: Sent instantly (0 hours).",
        "Primary Goal: Remove technical friction by offering free tariff calibration by our engineering desk within 4 hours.",
        "Expected Metric: >40% upload or reply rate with an Excel rate card attached."
    ])
    add_subject_box(doc, "Welcome to Quotelytics — Let's calibrate your first carrier tariff", "EMAIL SUBJECT LINE:")

    add_h2(doc, "Email Body Copy")
    doc.add_paragraph("Hi {{first_name}},")
    doc.add_paragraph("Welcome to Quotelytics! Your account has been provisioned and is active.")
    doc.add_paragraph(
        "Our goal is simple: eliminate the 15-minute manual spreadsheet scramble and give your dispatch desk sub-second multi-carrier rate comparisons."
    )
    
    doc.add_paragraph("To get started, you have two quick options:")
    
    b1 = doc.add_paragraph(style='List Bullet')
    b1.add_run("Option 1 (DIY in 60 seconds): ").bold = True
    b1.add_run("Log in to your console at https://quotelytics.ca/console/rate-sheets and drag & drop one of your carrier Excel tariffs (.xlsx or .csv). Our system will auto-detect the weight breaks and FSA matrix for your approval.")
    
    b2 = doc.add_paragraph(style='List Bullet')
    b2.add_run("Option 2 (White-Glove Calibration - Recommended): ").bold = True
    b2.add_run("Simply reply to this email with 1 or 2 of your messy carrier Excel tariffs attached. Our dispatch engineering desk will calibrate, test, and activate them in your account within 4 business hours—completely free of charge.")

    doc.add_paragraph("Want to test a quote right now before uploading anything?")
    doc.add_paragraph("Check out our interactive test sandbox pre-loaded with synthetic Canadian LTL tariffs:")
    
    p_link = doc.add_paragraph()
    p_link.paragraph_format.left_indent = Inches(0.25)
    r = p_link.add_run("👉 https://quotelytics.ca/demo")
    r.bold = True
    r.font.color.rgb = RGBColor(14, 116, 144)

    doc.add_paragraph("If you run into any questions or have an unusual tariff structure, reply to this email or call my direct line at 289-929-8565.")
    doc.add_paragraph("Glad to have {{company_name}} on board!")
    
    psig = doc.add_paragraph()
    psig.add_run("Dylan\n").bold = True
    psig.add_run("Founder & Product Engineer | Quotelytics Inc.\n")
    psig.add_run("support@quotelytics.ca • Direct: 289-929-8565\n")
    psig.add_run("https://quotelytics.ca")

    add_casl_footer_box(doc)

    path = os.path.join(OUTREACH_DIR, "08_Drip_Email_Day_0_Welcome_and_Tariff_Calibration.docx")
    doc.save(path)
    return path

def build_doc_09():
    doc = Document()
    format_doc_defaults(doc, "Onboarding Drip: Day 3 Deficit Rating Pro-Tip")
    add_header_banner(
        doc,
        "Drip Email 2 (Day 3): Pro-Tip — Deficit Rating Magic",
        "Educational engagement email sent 3 days after signup to highlight mathematical precision and cost savings.",
        "AUTOMATED ONBOARDING DRIP SEQUENCE"
    )
    add_callout(doc, "Trigger & Objectives", [
        "Trigger: Day 3 after account creation if user has logged in at least once.",
        "Timing: 72 hours post-registration (sent at 9:00 AM local time).",
        "Primary Goal: Educate dispatchers on deficit rating logic and show how Quotelytics prevents $20-$50 shipper overcharges.",
        "Call to Action: Try rating an 850 lb shipment in the console."
    ])
    add_subject_box(doc, "Pro-Tip: How Deficit Rating saves your shippers $20 to $50 per quote", "EMAIL SUBJECT LINE:")

    add_h2(doc, "Email Body Copy")
    doc.add_paragraph("Hi {{first_name}},")
    doc.add_paragraph("Quick question: have you ever had a customer ask to ship an 850 lb skid from Toronto to Calgary?")
    doc.add_paragraph(
        "In most carrier tariffs, the base rate at the 500 lb break might be $24.50/CWT, while the rate at the 1,000 lb break drops to $18.20/CWT."
    )
    doc.add_paragraph("If your dispatcher rates 850 lbs at the actual weight:")
    
    bp1 = doc.add_paragraph(style='List Bullet')
    bp1.add_run("Actual Weight Billing: (850 lbs / 100) × $24.50 = ").bold = True
    bp1.add_run("$208.25")
    
    doc.add_paragraph("Under standard Canadian LTL tariff rules, however, carriers allow deficit rating:")
    
    bp2 = doc.add_paragraph(style='List Bullet')
    bp2.add_run("Deficit Rating Break: (1,000 lbs / 100) × $18.20 = ").bold = True
    bp2.add_run("$182.00  (A clean $26.25 savings!)")

    doc.add_paragraph(
        "Doing this mental math across 5 different carrier spreadsheets under pressure is where dispatch mistakes happen. Quotelytics checks every discount bracket automatically in 0.02ms, ensuring you never overcharge a shipper or lose a bid."
    )
    
    doc.add_paragraph("Try running an 850 lb lane in your console right now:")
    
    p_link = doc.add_paragraph()
    p_link.paragraph_format.left_indent = Inches(0.25)
    r = p_link.add_run("👉 https://quotelytics.ca/console/new-quote")
    r.bold = True
    r.font.color.rgb = RGBColor(14, 116, 144)

    doc.add_paragraph("How is the platform feeling for your dispatch desk so far? Hit reply and let me know!")
    doc.add_paragraph("Cheers,")
    
    psig = doc.add_paragraph()
    psig.add_run("Dylan\n").bold = True
    psig.add_run("Quotelytics Inc. • support@quotelytics.ca • 289-929-8565\n")
    psig.add_run("https://quotelytics.ca")

    add_casl_footer_box(doc)

    path = os.path.join(OUTREACH_DIR, "09_Drip_Email_Day_3_Deficit_Rating_Tip.docx")
    doc.save(path)
    return path

def build_doc_10():
    doc = Document()
    format_doc_defaults(doc, "Onboarding Drip: Day 7 Proposal PDF Walkthrough")
    add_header_banner(
        doc,
        "Drip Email 3 (Day 7): 1-Click Client Rate Proposals",
        "Feature highlight and commercial pre-sell email sent 7 days after signup.",
        "AUTOMATED ONBOARDING DRIP SEQUENCE"
    )
    add_callout(doc, "Trigger & Objectives", [
        "Trigger: Day 7 after registration.",
        "Timing: 168 hours post-registration.",
        "Primary Goal: Introduce the 1-Click Client Proposal PDF generator with custom margin markups.",
        "Commercial Goal: Introduce the Founding Customer 30% discount coupon (FOUNDING25) before beta concludes."
    ])
    add_subject_box(doc, "New Feature: Turn any ranked rate into a branded Client Proposal in 1 click", "EMAIL SUBJECT LINE:")

    add_h2(doc, "Email Body Copy")
    doc.add_paragraph("Hi {{first_name}},")
    doc.add_paragraph(
        "Hope your dispatch team has had a productive week! We wanted to highlight one of our most popular workflow tools in Quotelytics:"
    )
    
    p_lead = doc.add_paragraph()
    r = p_lead.add_run("1-Click Client Rate Proposal Generator")
    r.bold = True
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor(15, 41, 66)

    doc.add_paragraph(
        "Instead of retyping numbers from your screen into an email or Word doc to send to your customer:"
    )
    
    b1 = doc.add_paragraph(style='List Bullet')
    b1.add_run("Toggle your desired markup: ").bold = True
    b1.add_run("Add a flat dollar amount (e.g. +$125) or a gross margin percentage (e.g. +15%).")
    
    b2 = doc.add_paragraph(style='List Bullet')
    b2.add_run("Click 'Export Client Proposal PDF': ").bold = True
    b2.add_run("Instantly download a clean, professional rate confirmation sheet branded for {{company_name}}, complete with Canadian tax breakdowns (HST/GST/QST) and shipment validity dates.")

    doc.add_paragraph("You can test this right now on any generated quote:")
    p_link = doc.add_paragraph()
    p_link.paragraph_format.left_indent = Inches(0.25)
    r = p_link.add_run("👉 https://quotelytics.ca/console/new-quote")
    r.bold = True
    r.font.color.rgb = RGBColor(14, 116, 144)

    doc.add_paragraph(
        "As a reminder, our Founding Customer Program is open until the end of the month. Use coupon code FOUNDING25 to lock in 30% off Broker Pro ($55 CAD/mo instead of $79 CAD/mo) for your entire first year."
    )
    doc.add_paragraph("Would you have 10 minutes next week to share any feedback on what we should build next?")
    doc.add_paragraph("Best regards,")

    psig = doc.add_paragraph()
    psig.add_run("Dylan\n").bold = True
    psig.add_run("Founder & Product Engineer | Quotelytics Inc.\n")
    psig.add_run("support@quotelytics.ca • Direct: 289-929-8565\n")
    psig.add_run("https://quotelytics.ca")

    add_casl_footer_box(doc)

    path = os.path.join(OUTREACH_DIR, "10_Drip_Email_Day_7_Proposal_PDF_Walkthrough.docx")
    doc.save(path)
    return path


# -------------------------------------------------------------
# Canadian Freight Brokerage Target Prospect Tracker
# -------------------------------------------------------------
PROSPECTS_DATA = [
    {
        "Brokerage Name": "Polaris Global Logistics (Polaris Transportation Group)",
        "City": "Mississauga",
        "Province": "ON",
        "Postal FSA": "L5T 2B7",
        "Est Dispatchers": "15–30",
        "Primary Freight Specialization": "Ontario-Quebec LTL & Cross-Border USA",
        "Target Role": "VP of Operations / Logistics Director",
        "Recommended Template": "Template 1 (Owners / Ops Directors)",
        "Public Website": "https://www.polaristransport.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Major Canadian LTL provider with extensive cross-border brokerage division."
    },
    {
        "Brokerage Name": "Titanium Logistics (Titanium Transportation Group)",
        "City": "Bolton",
        "Province": "ON",
        "Postal FSA": "L7E 5S4",
        "Est Dispatchers": "20–40",
        "Primary Freight Specialization": "Intra-Canada LTL, Truckload & 3PL Brokerage",
        "Target Role": "Lead LTL Dispatcher / Operations Manager",
        "Recommended Template": "Template 2 (Dispatch Managers)",
        "Public Website": "https://www.ttgi.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Publicly traded Canadian carrier/broker with active dispatch desks across Ontario."
    },
    {
        "Brokerage Name": "Challenger Logistics (Challenger Motor Freight)",
        "City": "Cambridge",
        "Province": "ON",
        "Postal FSA": "N3H 4R7",
        "Est Dispatchers": "15–25",
        "Primary Freight Specialization": "Transcontinental Canadian LTL & Specialized",
        "Target Role": "Director of 3PL Logistics",
        "Recommended Template": "Template 1 (Owners / Ops Directors)",
        "Public Website": "https://www.challenger.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Significant non-asset 3PL division managing third-party carrier spreadsheets."
    },
    {
        "Brokerage Name": "Fastfrate Integrated Logistics",
        "City": "Woodbridge",
        "Province": "ON",
        "Postal FSA": "L4H 1X9",
        "Est Dispatchers": "10–20",
        "Primary Freight Specialization": "East-to-West LTL Intermodal & Road Brokerage",
        "Target Role": "Dispatch Manager / Pricing Specialist",
        "Recommended Template": "Template 2 (Dispatch Managers)",
        "Public Website": "https://www.fastfrate.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Heavy transcontinental Canada lane volume (Toronto -> Calgary / Vancouver)."
    },
    {
        "Brokerage Name": "Manitoulin Global Forwarding",
        "City": "Mississauga",
        "Province": "ON",
        "Postal FSA": "L5T 1W6",
        "Est Dispatchers": "10–25",
        "Primary Freight Specialization": "Freight Forwarding, LTL Rating & 3PL Distribution",
        "Target Role": "Freight Forwarding Account Executive",
        "Recommended Template": "Template 3 (Freight Forwarders / AEs)",
        "Public Website": "https://www.mgf.ca",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Forwarding arm regularly issues client quote proposals across carrier tariffs."
    },
    {
        "Brokerage Name": "Nulogx Inc. (Transportation Management)",
        "City": "Oakville",
        "Province": "ON",
        "Postal FSA": "L6H 5R7",
        "Est Dispatchers": "5–15",
        "Primary Freight Specialization": "Managed Transportation, Freight Audit & Rating",
        "Target Role": "Director of Carrier Management & Pricing",
        "Recommended Template": "Template 1 (Owners / Ops Directors)",
        "Public Website": "https://www.nulogx.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Audit and 3PL consultancy obsessed with tariff precision and deficit rules."
    },
    {
        "Brokerage Name": "APPS Transport Group (APPS Logistics Desk)",
        "City": "Mississauga",
        "Province": "ON",
        "Postal FSA": "L5T 2N7",
        "Est Dispatchers": "8–18",
        "Primary Freight Specialization": "Ontario / Quebec / Western Canada Express LTL",
        "Target Role": "LTL Freight Brokerage Manager",
        "Recommended Template": "Template 2 (Dispatch Managers)",
        "Public Website": "https://www.appsexpress.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Operates active 3PL brokerage desk supplementing asset network."
    },
    {
        "Brokerage Name": "Caravan Logistics Inc.",
        "City": "Oakville",
        "Province": "ON",
        "Postal FSA": "L6H 6M7",
        "Est Dispatchers": "10–20",
        "Primary Freight Specialization": "Dry Van, LTL Freight & Cross-Border Logistics",
        "Target Role": "Logistics Operations Lead",
        "Recommended Template": "Template 1 (Owners / Ops Directors)",
        "Public Website": "https://www.caravanlogistics.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Medium-sized Ontario 3PL looking to optimize dispatcher turnaround time."
    },
    {
        "Brokerage Name": "Maritime-Ontario Freight Lines (Logistics Div)",
        "City": "Brampton",
        "Province": "ON",
        "Postal FSA": "L6T 4K3",
        "Est Dispatchers": "10–25",
        "Primary Freight Specialization": "Trans-Canada Cold & Dry LTL Brokerage",
        "Target Role": "Account Manager / Pricing Coordinator",
        "Recommended Template": "Template 3 (Freight Forwarders / AEs)",
        "Public Website": "https://www.m-o.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Atlantic Canada to Ontario & Western Canada specialized lanes."
    },
    {
        "Brokerage Name": "Transport Bourassa 3PL Logistics",
        "City": "Saint-Jean-sur-Richelieu",
        "Province": "QC",
        "Postal FSA": "J3B 7G4",
        "Est Dispatchers": "6–14",
        "Primary Freight Specialization": "Quebec-Ontario LTL & Heated/Reefer Service",
        "Target Role": "Directeur des Opérations / VP Operations",
        "Recommended Template": "Template 1 (Owners / Ops Directors)",
        "Public Website": "https://www.bourassa.ca",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Bilingual team handling high-density Montreal to GTA freight corridor."
    },
    {
        "Brokerage Name": "Overland West Freight Lines (3PL Division)",
        "City": "Calgary",
        "Province": "AB",
        "Postal FSA": "T2P 3M4",
        "Est Dispatchers": "5–12",
        "Primary Freight Specialization": "Western Canadian LTL (BC, AB, SK, MB)",
        "Target Role": "Regional Dispatch Manager",
        "Recommended Template": "Template 2 (Dispatch Managers)",
        "Public Website": "https://www.overlandwest.ca",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Focus on Calgary, Edmonton, Vancouver and Saskatoon distribution."
    },
    {
        "Brokerage Name": "VersaCold Logistics Services (Brokerage)",
        "City": "Vaughan",
        "Province": "ON",
        "Postal FSA": "L4K 4V8",
        "Est Dispatchers": "12–25",
        "Primary Freight Specialization": "Temperature-Sensitive & Ambient LTL 3PL",
        "Target Role": "Pricing Manager / Account Executive",
        "Recommended Template": "Template 3 (Freight Forwarders / AEs)",
        "Public Website": "https://www.versacold.com",
        "Status": "Not Contacted",
        "Date Contacted": "",
        "Follow-Up Date": "",
        "Demo Date": "",
        "Notes": "Generates client proposals for food and cold-chain corporate shippers."
    }
]

def build_prospects_tracker():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Target Canadian Brokerages"
    
    headers = [
        "Brokerage Name", "HQ City", "Province", "Postal FSA", "Est. Dispatchers",
        "Primary Freight Specialization", "Target Role", "Recommended Template",
        "Public Directory Website", "Outreach Status", "Date Contacted",
        "Follow-Up Date", "Demo Scheduled", "Notes & Feedback"
    ]
    
    # Title row
    ws.merge_cells("A1:N1")
    title_cell = ws["A1"]
    title_cell.value = "Quotelytics Inc. — Canadian Freight Brokerage Cold Outreach Target Directory (CASL s. 10(9)(b))"
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color="0F2942", end_color="0F2942", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36
    
    # Header row
    ws.row_dimensions[2].height = 28
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style='thin', color="CBD5E1"),
        right=Side(style='thin', color="CBD5E1"),
        top=Side(style='thin', color="CBD5E1"),
        bottom=Side(style='thin', color="CBD5E1")
    )
    
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_idx)
        cell.value = h
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    # Data rows
    alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    regular_font = Font(name="Calibri", size=10.5, color="1E293B")
    
    for r_idx, prospect in enumerate(PROSPECTS_DATA, 3):
        ws.row_dimensions[r_idx].height = 24
        is_even = (r_idx % 2 == 0)
        
        row_values = [
            prospect["Brokerage Name"],
            prospect["City"],
            prospect["Province"],
            prospect["Postal FSA"],
            prospect["Est Dispatchers"],
            prospect["Primary Freight Specialization"],
            prospect["Target Role"],
            prospect["Recommended Template"],
            prospect["Public Website"],
            prospect["Status"],
            prospect["Date Contacted"],
            prospect["Follow-Up Date"],
            prospect["Demo Date"],
            prospect["Notes"]
        ]
        
        for c_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            cell.value = val
            cell.font = regular_font
            cell.border = thin_border
            if is_even:
                cell.fill = alt_fill
            
            # Alignments
            if c_idx in [2, 3, 4, 5, 10, 11, 12, 13]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    # Column widths
    col_widths = {
        1: 34, 2: 18, 3: 12, 4: 14, 5: 18,
        6: 38, 7: 30, 8: 30, 9: 28, 10: 16,
        11: 16, 12: 16, 13: 18, 14: 45
    }
    for col_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A3"
    
    xlsx_path = os.path.join(OUTREACH_DIR, "Canadian_Freight_Brokerage_Target_Prospects.xlsx")
    wb.save(xlsx_path)

    # Also export CSV version
    csv_path = os.path.join(OUTREACH_DIR, "Canadian_Freight_Brokerage_Target_Prospects.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for p in PROSPECTS_DATA:
            writer.writerow([
                p["Brokerage Name"], p["City"], p["Province"], p["Postal FSA"],
                p["Est Dispatchers"], p["Primary Freight Specialization"],
                p["Target Role"], p["Recommended Template"], p["Public Website"],
                p["Status"], p["Date Contacted"], p["Follow-Up Date"],
                p["Demo Date"], p["Notes"]
            ])

    return xlsx_path, csv_path


def main():
    os.makedirs(OUTREACH_DIR, exist_ok=True)
    print("Building full Quotelytics Outreach & Lead Generation Suite...")
    
    docs = [
        build_doc_00(),
        build_doc_01(),
        build_doc_02(),
        build_doc_03(),
        build_doc_04(),
        build_doc_05(),
        build_doc_06(),
        build_doc_07(),
        build_doc_08(),
        build_doc_09(),
        build_doc_10(),
    ]
    for d in docs:
        print(f"Generated DOCX: {os.path.basename(d)}")
        
    xlsx, csv_f = build_prospects_tracker()
    print(f"Generated XLSX: {os.path.basename(xlsx)}")
    print(f"Generated CSV:  {os.path.basename(csv_f)}")
    print("\nComplete Outreach Suite successfully built in outreach/!")

if __name__ == "__main__":
    main()
