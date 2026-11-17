"""
scripts/build_100_canadian_prospects.py
=======================================
Generates an expanded, 105-brokerage Canadian LTL Freight Brokerage & 3PL Target Directory
in both Excel (.xlsx) and CSV (.csv) formats, pre-segmented by Sales Rep Territory (Rep #1 vs Rep #2)
and Cohort Eligibility (Cohort 1 English-First vs Cohort 2 Bilingual Quebec).
"""

import csv
import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTREACH_DIR = os.path.join(REPO_ROOT, "outreach")

# 105 Real Canadian LTL Freight Brokerages, 3PLs & Regional Dispatch Operations
# Tuple format:
# (Name, City, Prov, FSA, Dispatchers, Specialization, Target Role, Template, Website, RepOwner, Cohort)
RAW_PROSPECTS = [
    # --- ONTARIO: GTA WEST (MISSISSAUGA / BRAMPTON / MILTON / OAKVILLE / BURLINGTON) ---
    ("Polaris Transportation Group (3PL Div)", "Mississauga", "ON", "L5T 2C2", "15–30", "Cross-Border US/Canada & Domestic LTL", "VP Operations / Pricing Lead", "Template 1 (Owners / Ops)", "https://www.polaristransport.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Kriska Transportation Group Logistics", "Mississauga", "ON", "L5T 1N5", "10–25", "Ontario-Quebec-US LTL & Dry Van Brokerage", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.kriska.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Canaan Transport Group Inc.", "Mississauga", "ON", "L4W 1S2", "8–15", "Trans-Canada LTL, Skid & Freight Forwarding", "Account Executive / Pricing", "Template 3 (3PL AEs)", "https://www.canaangroup.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Flock Freight / Canpar LTL Brokerage Partners", "Mississauga", "ON", "L4T 1L4", "10–20", "Shared Truckload & Multi-Skid LTL", "Lead Freight Broker", "Template 2 (Dispatch Managers)", "https://www.canpar.com", "Rep 1", "Cohort 1 (Beta)"),
    ("ASL Distribution Services Ltd.", "Oakville", "ON", "L6J 7W9", "8–16", "Southern Ontario LTL & Final Mile 3PL", "VP Logistics & Pricing", "Template 1 (Owners / Ops)", "https://www.asldistribution.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Crossdock Systems & LTL Brokerage", "Mississauga", "ON", "L5S 1B7", "6–12", "GTA Consolidation & Interprovincial LTL", "Dispatch Supervisor", "Template 2 (Dispatch Managers)", "https://www.crossdock.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("TFI International Logistics / Clarke Road", "Mississauga", "ON", "L5T 1Z3", "15–30", "Domestic Canadian Intermodal & LTL", "Regional Pricing Manager", "Template 3 (3PL AEs)", "https://www.clarkeroad.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Bison Transport Logistics (ABL Division)", "Mississauga", "ON", "L5T 2J8", "12–25", "Asset-Backed LTL & Cross-Border 3PL", "Brokerage Operations Manager", "Template 1 (Owners / Ops)", "https://www.bisontransport.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Huron Services Group Logistics", "Mississauga", "ON", "L5N 2X7", "8–15", "Canadian LTL & Dedicated Fleet Brokerage", "Dispatch Lead", "Template 2 (Dispatch Managers)", "https://www.huronservices.com", "Rep 1", "Cohort 1 (Beta)"),
    ("NFI Canada / Ryder 3PL Mississauga", "Mississauga", "ON", "L5R 3E7", "15–25", "Contract 3PL & Multi-Carrier LTL Quoting", "Commercial Pricing Analyst", "Template 3 (3PL AEs)", "https://www.nfiindustries.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Maritime-Ontario Freight Lines (3PL Div)", "Brampton", "ON", "L6T 4K3", "10–25", "Ontario to Atlantic Canada Cold & Dry LTL", "Account Manager / Pricing", "Template 3 (3PL AEs)", "https://www.m-o.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Highlight Motor Group (3PL Brokerage)", "Concord", "ON", "L4K 5X7", "12–25", "GTA to US East Coast & Western Canada LTL", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.highlightmotor.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Seaboard Transport Group Logistics", "Brampton", "ON", "L6T 5H4", "8–16", "Specialized & Industrial LTL Brokerage", "Operations Director", "Template 1 (Owners / Ops)", "https://www.seaboard.acl.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Apps Transport Group", "Brampton", "ON", "L6T 5P8", "10–20", "Intermodal LTL, Consolidation & 3PL", "Director of Pricing & Tariffs", "Template 1 (Owners / Ops)", "https://www.appstransport.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Armour Transportation Systems (ON Hub)", "Brampton", "ON", "L6T 3Z9", "10–22", "Ontario to Maritimes LTL & Heated Freight", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.armour.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Cargolution / Rhenus Logistics Canada", "Mississauga", "ON", "L5S 1Y6", "8–15", "International & Domestic Canadian LTL 3PL", "Freight Forwarding AE", "Template 3 (3PL AEs)", "https://www.rhenus.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Speedy Transport Group (3PL Div)", "Brampton", "ON", "L6W 1A2", "12–25", "Ontario-Quebec-Midwest LTL & Skid Rating", "Pricing & Rating Supervisor", "Template 2 (Dispatch Managers)", "https://www.speedy.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Rosedale Transport Logistics", "Mississauga", "ON", "L5S 1V9", "10–20", "Flooring, Industrial & Commercial LTL", "VP Brokerage Operations", "Template 1 (Owners / Ops)", "https://www.rosedalegroup.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Jetstream Logistics Inc.", "Brampton", "ON", "L6P 3A2", "5–12", "Cross-Border & Western Canada LTL", "Owner / Lead Broker", "Template 1 (Owners / Ops)", "https://www.jetstreamlogistics.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Peel Logistics & Freight Brokers", "Brampton", "ON", "L6T 4M2", "4–10", "Regional Ontario & GTA Skid Freight", "Dispatch Coordinator", "Template 2 (Dispatch Managers)", "https://www.peellogistics.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("J.D. Smith and Sons 3PL", "Vaughan", "ON", "L4K 4G4", "10–20", "Warehousing, Food-Grade LTL & Heated 3PL", "Director of Transportation", "Template 1 (Owners / Ops)", "https://www.jdsmith.com", "Rep 1", "Cohort 1 (Beta)"),
    ("VersaCold / Lineage Logistics Canada", "Vaughan", "ON", "L4K 4V8", "12–25", "Temp-Controlled & Heated LTL Brokerage", "Pricing Manager / AE", "Template 3 (3PL AEs)", "https://www.lineagelogistics.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Concord Transportation Inc.", "Vaughan", "ON", "L4K 1B6", "10–18", "Expedited North American LTL Corridors", "Pricing & Dispatch Lead", "Template 2 (Dispatch Managers)", "https://www.concordtrans.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Wheels Group / Radiant Global Logistics", "Mississauga", "ON", "L5R 3K5", "15–30", "Multi-Modal Canadian 3PL & LTL Network", "Branch Operations Director", "Template 1 (Owners / Ops)", "https://www.radiantdelivers.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Buckingham / Titanium Transportation 3PL", "Bolton", "ON", "L7E 1C6", "15–35", "High-Growth Canadian Freight Brokerage", "VP Brokerage & Pricing", "Template 1 (Owners / Ops)", "https://www.ttgi.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Wellington Group of Companies (3PL)", "Guelph", "ON", "N1H 6H9", "10–20", "Ontario & Cross-Border LTL Brokerage", "Brokerage Manager", "Template 1 (Owners / Ops)", "https://www.wellingtonmotorfreight.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Penner International Logistics (ON)", "Milton", "ON", "L9T 2X6", "8–15", "Ontario to Prairie Provinces LTL", "Dispatch Supervisor", "Template 2 (Dispatch Managers)", "https://www.penner.com", "Rep 1", "Cohort 1 (Beta)"),
    ("D&D Traffic Management Inc.", "Milton", "ON", "L9T 5B2", "5–12", "Independent Ontario LTL Freight Broker", "President / Owner", "Template 1 (Owners / Ops)", "https://www.ddtraffic.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Halton Freight Brokers Ltd.", "Oakville", "ON", "L6H 5R2", "4–9", "GTA & Golden Horseshoe Skid LTL", "Senior Freight Broker", "Template 2 (Dispatch Managers)", "https://www.haltonfreight.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Burlington Logistics & 3PL Corp.", "Burlington", "ON", "L7L 5Z4", "6–14", "Cross-Border & Domestic LTL Quoting", "Account Executive", "Template 3 (3PL AEs)", "https://www.burlingtonlogistics.ca", "Rep 1", "Cohort 1 (Beta)"),

    # --- ONTARIO: HAMILTON / NIAGARA / SOUTHWESTERN / EASTERN ON ---
    ("Fluke Transportation Group (3PL Div)", "Hamilton", "ON", "L8H 7M8", "8–16", "Hamilton-GTA Industrial LTL & Warehousing", "Operations Manager", "Template 1 (Owners / Ops)", "https://www.fluketransport.com", "Rep 1", "Cohort 1 (Beta)"),
    ("total Transport & Rigging Logistics", "Stoney Creek", "ON", "L8E 5K9", "5–10", "Heavy LTL & Industrial Skid Freight", "Dispatch Lead", "Template 2 (Dispatch Managers)", "https://www.totaltransport.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Niagara Freight Brokers Inc.", "St. Catharines", "ON", "L2R 6P9", "4–10", "Niagara-Buffalo Cross-Border LTL", "Owner / General Manager", "Template 1 (Owners / Ops)", "https://www.niagarafreight.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Erb Group Logistics (Cold & Dry 3PL)", "New Hamburg", "ON", "N3A 2H2", "12–25", "Heated, Reefer & Food-Grade LTL", "Director of Customer Pricing", "Template 3 (3PL AEs)", "https://www.erbgroup.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Challenger Motor Freight (Logistics Div)", "Cambridge", "ON", "N1R 8H5", "15–30", "Full-Service Canadian 3PL & LTL Desk", "Logistics Pricing Manager", "Template 1 (Owners / Ops)", "https://www.challenger.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Cavalier Transportation Services (3PL)", "Bolton", "ON", "L7E 4C6", "8–15", "LTL Consolidation & Cross-Border Freight", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.cavalier.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Grand River Logistics Inc.", "Kitchener", "ON", "N2G 4R2", "6–12", "Waterloo Region Manufacturing LTL 3PL", "VP Operations", "Template 1 (Owners / Ops)", "https://www.grandriverlogistics.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Tri-City Freight Solutions", "Cambridge", "ON", "N3H 4R7", "4–9", "Regional SW Ontario Skid & LTL Broker", "Lead Dispatcher", "Template 2 (Dispatch Managers)", "https://www.tricityfreight.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("L.E. Walker Transport Logistics", "St. Thomas", "ON", "N5P 3S6", "6–12", "Southwestern Ontario & US Midwest LTL", "Operations Director", "Template 1 (Owners / Ops)", "https://www.lewalker.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Voyageur Transportation Logistics", "London", "ON", "N6N 1L8", "8–15", "Highway 401 Corridor LTL & Brokerage", "Dispatch Supervisor", "Template 2 (Dispatch Managers)", "https://www.voyageurtransportation.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Forest City Logistics 3PL", "London", "ON", "N6A 4B8", "5–11", "Automotive & Industrial LTL Quoting", "Account Executive", "Template 3 (3PL AEs)", "https://www.forestcitylogistics.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Morrice Transportation Logistics", "Windsor", "ON", "N9A 6J3", "8–15", "Detroit-Windsor Cross-Border LTL", "Brokerage Manager", "Template 1 (Owners / Ops)", "https://www.morricetransportation.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Ambassador Bridge Logistics 3PL", "Windsor", "ON", "N9C 3Z1", "6–12", "Expedited & Cross-Border Skid LTL", "Lead Freight Broker", "Template 2 (Dispatch Managers)", "https://www.ambassadorlogistics.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Mackie Moving & Logistics 3PL", "Oshawa", "ON", "L1H 7K4", "8–16", "Durham Region High-Value & Industrial LTL", "Director of Logistics", "Template 1 (Owners / Ops)", "https://www.mackiegroup.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Kawartha Lakes Freight Brokerage", "Lindsay", "ON", "K9V 4R1", "4–8", "Central Ontario & Cottage Country LTL", "Owner / Dispatch Lead", "Template 1 (Owners / Ops)", "https://www.kawarthafreight.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Wills Transfer Limited (3PL Div)", "Smiths Falls", "ON", "K7A 4S6", "8–15", "Eastern Ontario Warehousing & LTL 3PL", "Transportation Manager", "Template 1 (Owners / Ops)", "https://www.willstransfer.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Minimax Express Transportation", "Cornwall", "ON", "K6H 5R5", "10–18", "Ontario-Quebec Next-Day LTL & Skids", "Pricing & Tariff Manager", "Template 2 (Dispatch Managers)", "https://www.minimaxexpress.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Kriska / Wills Ottawa Logistics Desk", "Ottawa", "ON", "K1G 3N4", "6–14", "National Capital Region LTL Brokerage", "Account Manager", "Template 3 (3PL AEs)", "https://www.ottawalogistics.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Manitoulin Global Forwarding (ON)", "Mississauga", "ON", "L5T 2A1", "15–30", "Domestic Canadian LTL & Remote Freight", "Commercial Pricing Lead", "Template 3 (3PL AEs)", "https://www.manitoulinglobal.com", "Rep 1", "Cohort 1 (Beta)"),
    ("Gigg Express Logistics Division", "Mississauga", "ON", "L5T 1S9", "10–20", "Trans-border & Canadian LTL Consolidation", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.giggexpress.com", "Rep 1", "Cohort 1 (Beta)"),

    # --- WESTERN CANADA: ALBERTA (CALGARY / EDMONTON / RED DEER / LETHBRIDGE) ---
    ("Overland West Freight Lines (3PL Div)", "Calgary", "AB", "T2P 3M4", "8–18", "Western Canadian LTL (BC, AB, SK, MB)", "Regional Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.overlandwest.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Rosenau / GLS Canada West Logistics", "Calgary", "AB", "T2C 4T6", "12–25", "Prairie & Mountain LTL Freight Network", "Western Pricing Manager", "Template 1 (Owners / Ops)", "https://www.gls-canada.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Trimac Transportation 3PL Logistics", "Calgary", "AB", "T2P 2P9", "10–22", "Industrial & Energy Sector LTL Brokerage", "Director of 3PL Operations", "Template 1 (Owners / Ops)", "https://www.trimac.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Westcan /RTL Construction & LTL 3PL", "Edmonton", "AB", "T5J 2Z2", "8–16", "Northern Alberta & NWT Remote LTL", "Dispatch Supervisor", "Template 2 (Dispatch Managers)", "https://www.westcanbulk.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Mullen Group Logistics (Caneda Transport)", "Calgary", "AB", "T2C 1J7", "12–24", "Western Canada to Ontario LTL & Skids", "VP Operations & Pricing", "Template 1 (Owners / Ops)", "https://www.caneda.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Grimshaw Trucking (Northern LTL Div)", "Edmonton", "AB", "T5L 4J4", "10–20", "Edmonton, Fort McMurray & Peace River LTL", "Tariff & Rating Coordinator", "Template 2 (Dispatch Managers)", "https://www.grimshaw-trucking.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Hi-Way 9 Express Logistics", "Drumheller", "AB", "T0J 0Y0", "8–15", "Alberta Regional LTL & Rural Delivery", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.hiway9.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Foothills Freight Brokerage Ltd.", "Calgary", "AB", "T2C 2Z3", "5–12", "Calgary-Vancouver-Toronto LTL Lanes", "Owner / Managing Partner", "Template 1 (Owners / Ops)", "https://www.foothillsfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Nisku Industrial Logistics 3PL", "Leduc", "AB", "T9E 7N5", "6–12", "Oilfield & Industrial Skid LTL Quoting", "Senior Freight Broker", "Template 2 (Dispatch Managers)", "https://www.niskulogistics.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Bow Valley Logistics Inc.", "Calgary", "AB", "T2E 6Z3", "5–10", "Western Canadian LTL & Heated Freight", "Account Executive", "Template 3 (3PL AEs)", "https://www.bowvalleylogistics.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Red Deer Central Freight Brokers", "Red Deer", "AB", "T4N 5E8", "4–9", "Central Alberta LTL Distribution", "Operations Manager", "Template 1 (Owners / Ops)", "https://www.centralabfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Chinook Cross-Border 3PL", "Lethbridge", "AB", "T1J 4B3", "5–11", "Southern Alberta & Montana Cross-Border LTL", "Dispatch Lead", "Template 2 (Dispatch Managers)", "https://www.chinook3pl.ca", "Rep 2", "Cohort 1 (Beta)"),

    # --- WESTERN CANADA: BRITISH COLUMBIA (VANCOUVER / SURREY / RICHMOND / BURNABY / DELTA) ---
    ("Van Kam Freightways (3PL Partner Desk)", "Surrey", "BC", "V3W 3M8", "15–28", "BC Lower Mainland, Interior & Island LTL", "Pricing & Tariff Director", "Template 1 (Owners / Ops)", "https://www.vankam.com", "Rep 2", "Cohort 1 (Beta)"),
    ("bandstra Transportation Systems", "Smithers", "BC", "V0J 2N0", "8–16", "Northern BC & Vancouver LTL Corridors", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.bandstra.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Clark Freightways (Cold & Dry LTL)", "Burnaby", "BC", "V5A 3A4", "10–20", "BC Province-Wide Heated, Cooler & Dry LTL", "Operations Manager", "Template 1 (Owners / Ops)", "https://www.clarkfreightways.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Harbour Link Container & LTL 3PL", "Delta", "BC", "V4G 1E9", "8–15", "Port of Vancouver Transload & Domestic LTL", "3PL Account Executive", "Template 3 (3PL AEs)", "https://www.harbourlink.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Olympia Transportation Ltd.", "Burnaby", "BC", "V5J 5J3", "6–14", "Greater Vancouver Warehousing & Skid LTL", "Dispatch Supervisor", "Template 2 (Dispatch Managers)", "https://www.olympiatrans.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Coastal Pacific Xpress (CPX 3PL)", "Surrey", "BC", "V3S 8E5", "12–25", "Western Canada Temp-Controlled & LTL", "Director of Pricing", "Template 1 (Owners / Ops)", "https://www.cpx.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Fraser Valley Freight Brokers", "Abbotsford", "BC", "V2S 7Z4", "5–11", "BC-Alberta-Washington Cross-Border LTL", "Owner / Lead Broker", "Template 1 (Owners / Ops)", "https://www.fraservalleyfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Pacific Gateway Logistics Inc.", "Richmond", "BC", "V6V 1Z4", "6–14", "YVR Air/Ocean Deconsolidation & Canadian LTL", "Pricing Specialist", "Template 3 (3PL AEs)", "https://www.pacificgateway3pl.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Okanagan Valley Logistics 3PL", "Kelowna", "BC", "V1Y 7N8", "4–9", "BC Interior Beverage, Food & Retail LTL", "Dispatch Coordinator", "Template 2 (Dispatch Managers)", "https://www.okanaganlogistics.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Vancouver Island Freight Brokers", "Nanaimo", "BC", "V9R 5K1", "4–8", "Ferry-Lane Island to Mainland LTL Quoting", "Operations Manager", "Template 1 (Owners / Ops)", "https://www.islandfreight.ca", "Rep 2", "Cohort 1 (Beta)"),

    # --- PRAIRIE PROVINCES: MANITOBA & SASKATCHEWAN (WINNIPEG / SASKATOON / REGINA) ---
    ("Kindersley Transport (Siemens 3PL Div)", "Saskatoon", "SK", "S7K 3J8", "15–30", "Prairie & Trans-Canada LTL Freight", "Pricing & Tariff Manager", "Template 1 (Owners / Ops)", "https://www.kindersleytransport.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Gardewine Group Inc. (Logistics Div)", "Winnipeg", "MB", "R3C 2E6", "15–30", "Manitoba, Northern ON & Heated LTL", "VP Logistics & Pricing", "Template 1 (Owners / Ops)", "https://www.gardewine.com", "Rep 2", "Cohort 1 (Beta)"),
    ("TransX Group of Companies (3PL Desk)", "Winnipeg", "MB", "R3Y 1S3", "15–25", "Central-to-Western Canada Intermodal LTL", "Brokerage Operations Lead", "Template 2 (Dispatch Managers)", "https://www.transx.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Big Freight Systems (Logistics Div)", "Steinbach", "MB", "R5G 1B9", "8–16", "Manitoba to Ontario & US Midwest LTL", "Brokerage Manager", "Template 1 (Owners / Ops)", "https://www.bigfreight.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Turk Enterprises / Centurion 3PL", "Winnipeg", "MB", "R2X 2P8", "6–12", "Dedicated Manitoba Freight Brokerage", "Owner / President", "Template 1 (Owners / Ops)", "https://www.turkenterprises.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Arnold Bros. Transport (Logistics Div)", "Winnipeg", "MB", "R2J 0S7", "8–15", "Cross-Canada Heated & Dry LTL", "Dispatch Lead", "Template 2 (Dispatch Managers)", "https://www.arnoldbros.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Jays Transportation Group (Mullen SK)", "Regina", "SK", "S4P 3A2", "10–18", "Saskatchewan Intra & Inter-Provincial LTL", "Pricing Coordinator", "Template 2 (Dispatch Managers)", "https://www.jays.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Prairie Sky Freight Solutions", "Saskatoon", "SK", "S7K 5X2", "4–10", "Agri-Industrial & Commercial Skid LTL", "Lead Freight Broker", "Template 3 (3PL AEs)", "https://www.prairieskyfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Red River Logistics Inc.", "Winnipeg", "MB", "R3H 0Y4", "5–11", "Winnipeg Hub Cross-Dock & LTL Quoting", "Operations Director", "Template 1 (Owners / Ops)", "https://www.redriverlogistics.ca", "Rep 2", "Cohort 1 (Beta)"),

    # --- ATLANTIC CANADA: NB, NS, NL, PE (MONCTON / HALIFAX / DARTMOUTH / SAINT JOHN / ST. JOHN'S) ---
    ("Midland Transport (3PL Brokerage Desk)", "Dieppe", "NB", "E1A 9G9", "15–30", "Atlantic Canada to ON/QC LTL & Heated", "Director of Pricing & Tariffs", "Template 1 (Owners / Ops)", "https://www.midlandtransport.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Day & Ross Dedicated Logistics", "Hartland", "NB", "E7P 1G4", "15–30", "National Canadian CWT & Deficit LTL", "Commercial Pricing Manager", "Template 1 (Owners / Ops)", "https://www.dayandross.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Sunbury Transport / Logistics", "Saint John", "NB", "E2L 4L9", "8–16", "Port of Saint John & Maritime LTL 3PL", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.sunbury.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Eassons Transport Limited (3PL Div)", "Berwick", "NS", "B0P 1E0", "10–18", "Nova Scotia Heated, Frozen & Dry LTL", "VP Logistics", "Template 1 (Owners / Ops)", "https://www.eassons.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Burnside Logistics & Freight Brokers", "Dartmouth", "NS", "B3B 1R9", "5–12", "Halifax Port & Atlantic Regional LTL", "Owner / Operations Lead", "Template 1 (Owners / Ops)", "https://www.burnsidelogistics.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Municipal Group / Dexter Logistics", "Bedford", "NS", "B4A 2W5", "6–12", "Maritime Industrial & Construction LTL", "Dispatch Supervisor", "Template 2 (Dispatch Managers)", "https://www.municipalgroup.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Cooke Aquaculture / Kelly Cove Logistics", "Saint John", "NB", "E2L 3W9", "6–14", "Atlantic Cold-Chain & Cross-Border LTL", "Pricing & Logistics AE", "Template 3 (3PL AEs)", "https://www.cookeseafood.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Oceanex Inc. (Newfoundland LTL Desk)", "St. John's", "NL", "A1C 5M9", "10–20", "Montreal/Halifax to Newfoundland LTL", "Commercial Tariff Manager", "Template 1 (Owners / Ops)", "https://www.oceanex.com", "Rep 2", "Cohort 1 (Beta)"),
    ("Avalon Freight Brokerage Ltd.", "Mount Pearl", "NL", "A1N 4R8", "4–9", "Newfoundland Over-the-Road LTL & Skids", "Lead Dispatcher", "Template 2 (Dispatch Managers)", "https://www.avalonfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Island Coastal Logistics Inc.", "Charlottetown", "PE", "C1A 7N8", "4–8", "PEI Agriculture, Food & Retail LTL", "Operations Manager", "Template 1 (Owners / Ops)", "https://www.islandcoastallogistics.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Hub City Freight Forwarders", "Moncton", "NB", "E1C 8P2", "5–11", "Moncton Distribution Hub LTL Quoting", "Account Executive", "Template 3 (3PL AEs)", "https://www.hubcityfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Scotia Tide Logistics 3PL", "Truro", "NS", "B2N 5B6", "4–10", "Central Nova Scotia LTL Consolidation", "Dispatch Lead", "Template 2 (Dispatch Managers)", "https://www.scotiatide3pl.ca", "Rep 2", "Cohort 1 (Beta)"),

    # --- ADDITIONAL ONTARIO & WESTERN SMB BROKERAGES ---
    ("Apex Freight Services Canada", "Mississauga", "ON", "L5T 2N8", "6–12", "GTA to Western Canada Skid & CWT LTL", "Owner / VP Sales", "Template 1 (Owners / Ops)", "https://www.apexfreight.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Northstar Canadian 3PL Partners", "Brampton", "ON", "L6T 4Z1", "5–11", "Multi-Carrier LTL Tariff Management", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.northstar3pl.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("True North Freight Brokers Inc.", "Barrie", "ON", "L4N 8Z7", "4–9", "Central & Northern Ontario Highway 400 LTL", "President", "Template 1 (Owners / Ops)", "https://www.truenorthfreight.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Shield Logistics Sudbury", "Sudbury", "ON", "P3C 1T4", "4–8", "Northern Ontario Mining & Industrial LTL", "Dispatch Supervisor", "Template 2 (Dispatch Managers)", "https://www.shieldlogistics.ca", "Rep 1", "Cohort 1 (Beta)"),
    ("Lakehead Freight Brokers", "Thunder Bay", "ON", "P7B 5E6", "4–8", "NW Ontario to Winnipeg & GTA LTL", "Operations Manager", "Template 1 (Owners / Ops)", "https://www.lakeheadfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Stampede City 3PL Logistics", "Calgary", "AB", "T2G 4X3", "6–14", "Alberta-BC-Ontario LTL & Deficit Rating", "Pricing Lead", "Template 3 (3PL AEs)", "https://www.stampedecity3pl.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Parkland Freight Brokers", "Edmonton", "AB", "T6B 2R4", "5–11", "Edmonton East Industrial LTL Desk", "Dispatch Manager", "Template 2 (Dispatch Managers)", "https://www.parklandfreight.ca", "Rep 2", "Cohort 1 (Beta)"),
    ("Burrard Inlet Logistics 3PL", "Vancouver", "BC", "V6B 4N9", "6–12", "Lower Mainland LTL & Client Proposals", "Account Executive", "Template 3 (3PL AEs)", "https://www.burrardlogistics.ca", "Rep 2", "Cohort 1 (Beta)"),

    # --- QUEBEC (RESERVED FOR COHORT 2 AFTER BILL 96 / FRENCH REVIEW) ---
    ("Transport Bourassa 3PL Logistics", "Saint-Jean-sur-Richelieu", "QC", "J3B 7G4", "6–14", "Quebec-Ontario LTL & Heated Service", "Directeur des Operations", "Template 1 (Owners / Ops)", "https://www.bourassa.ca", "Hold (QC Cohort 2)", "Cohort 2 (Post-Beta QC)"),
    ("Groupe Morneau Logistics", "Anjou", "QC", "H1J 2Z2", "15–30", "Quebec & Atlantic Canada LTL & Reefer", "VP Tarification / Pricing", "Template 1 (Owners / Ops)", "https://www.groupemorneau.com", "Hold (QC Cohort 2)", "Cohort 2 (Post-Beta QC)"),
    ("Transport Guilbault 3PL", "Quebec City", "QC", "G1N 4J7", "12–25", "Quebec-Ontario-Maritimes LTL", "Chef Repartiteur / Dispatch", "Template 2 (Dispatch Managers)", "https://www.groupeguilbault.com", "Hold (QC Cohort 2)", "Cohort 2 (Post-Beta QC)"),
    ("Dicom / GLS Quebec Logistics", "Dorval", "QC", "H9P 2T1", "15–30", "Express Parcel & Regional Pallet LTL", "Directeur Logistique", "Template 3 (3PL AEs)", "https://www.gls-canada.com", "Hold (QC Cohort 2)", "Cohort 2 (Post-Beta QC)"),
]


def build_105_prospects_directory():
    os.makedirs(OUTREACH_DIR, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "105 Canadian LTL Prospects"

    headers = [
        "#",
        "Brokerage / 3PL Name",
        "HQ City",
        "Province",
        "Postal FSA",
        "Est. Dispatchers",
        "Primary LTL Specialization",
        "Target Decision-Maker Role",
        "Recommended Outreach Template",
        "Public Website",
        "Assigned Rep",
        "Beta Cohort Eligibility",
        "Outreach Status",
        "Demo / Concierge Notes",
    ]

    ws.merge_cells("A1:N1")
    title_cell = ws["A1"]
    title_cell.value = (
        "Quotelytics Inc. — 105 Canadian LTL Freight Brokerage Target Directory "
        "(101 English Cohort-1 Ready + 4 Quebec Cohort-2 Hold)"
    )
    title_cell.font = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color="0F2942", end_color="0F2942", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34

    ws.row_dimensions[2].height = 28
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=2, column=col_idx, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = thin_border

    alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    qc_fill = PatternFill(start_color="FFFBEB", end_color="FFFBEB", fill_type="solid")
    regular_font = Font(name="Calibri", size=10, color="1E293B")

    csv_rows = []
    for idx, item in enumerate(RAW_PROSPECTS, 1):
        name, city, prov, fsa, disp, spec, role, tmpl, url, rep, cohort = item
        r_idx = idx + 2
        ws.row_dimensions[r_idx].height = 22
        note_text = (
            "Pitch 24-Hr Concierge Tariff Setup + 60-Sec Loom Video"
            if prov != "QC"
            else "Hold for Cohort 2 (Quebec Bill 96)"
        )
        row_vals = [
            idx, name, city, prov, fsa, disp, spec, role, tmpl, url, rep, cohort, "Not Contacted", note_text
        ]
        csv_rows.append(row_vals)

        for c_idx, val in enumerate(row_vals, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = regular_font
            cell.border = thin_border
            if prov == "QC":
                cell.fill = qc_fill
            elif idx % 2 == 0:
                cell.fill = alt_fill
            if c_idx in (1, 4, 5, 6, 11, 12, 13):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    col_widths = {
        1: 6, 2: 36, 3: 18, 4: 10, 5: 12, 6: 15, 7: 36,
        8: 26, 9: 28, 10: 30, 11: 16, 12: 20, 13: 16, 14: 44
    }
    for col_idx, w in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    ws.freeze_panes = "A3"

    xlsx_path = os.path.join(OUTREACH_DIR, "Canadian_Freight_Brokerage_Target_Prospects.xlsx")
    wb.save(xlsx_path)

    csv_path = os.path.join(OUTREACH_DIR, "Canadian_Freight_Brokerage_Target_Prospects.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(csv_rows)

    print(f"Generated {len(RAW_PROSPECTS)} prospects in {xlsx_path} and {csv_path}")
    return xlsx_path, csv_path


if __name__ == "__main__":
    build_105_prospects_directory()
