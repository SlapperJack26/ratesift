# RateSift Agent — 50 Rate Sheet Templates & Formats Corpus

This corpus catalogs **50 distinct freight rate sheet formats and templates** spanning Canadian and North American road freight, LTL, FTL, courier/parcel, intermodal, drayage, ocean, air cargo, and specialized transport. 

It serves as the comprehensive benchmark and training/testing suite for the RateSift parsing and rating engines, ensuring strict compliance with all 32 RateSift Agent Rules.

---

## Template Analysis: Guide Template #1 (Day & Ross Canadian LTL/PTL Tariff)

* **Source File Reference:** User-provided Day & Ross customer tariff sheet (Customer: NAFF / North American Freight, Account #158437).
* **Tariff Identification:** Tariff `O-33545`, Revision `336`.
* **Validity Horizon:** Effective `2023-11-15` to Expiry `2024-04-30` (Enforces Rule 16).
* **Pricing Official:** Frank Carvell.
* **Layout Structure:**
  1. **Metadata Header:** Customer profile, account number, effective/expiry dates, pricing authority.
  2. **Terms & Conditions / Accessorial Surcharges (Rules 1–29):**
     - Surcharges: Flat fees (e.g., Appointment Delivery $20.00, Amazon Delivery $50.00, Ferry LTL $24.78 / $124.86 / $232.25 / $462.50).
     - Hourly Rates & Minimums: Weekend/Holiday $75/hr (min 4 hrs / $300), Lumper $35/hr (min 4 hrs).
     - CWT Fees: Reconsignment $6.50/cwt (min $70 / max $285), Tradeshow $4.15/cwt (min $167).
     - Percentage Surcharges: Protective service 18% (min $39.50), Declared valuation 2% over $2.00/lb CAD.
     - Waived Accessorials: Power Tailgate (Waived), Inside Pickup/Delivery (Waived), Purchased Transportation Surcharge (Waived).
     - Fuel Surcharge: 100% of Freight Carriers Association (FCA) Fuel LTL road index.
     - Dimensional & Density Rules: 10.00 lbs/cu ft up to 20 linear feet, thereafter 1,000 lbs per linear foot. Specific lane commodity exceptions (grinding wheels & grass seed @ 26 lbs/cu ft).
  3. **Multi-Table Matrix in a Single Document:**
     - **Table A (Point-to-Point LTL):** `Origin, Destination, MIN, LTL, CWT:1000, CWT:2000, CWT:5000, CWT:10000, CWT:20000`.
     - **Table B (Between Localities LTL):** Origin and destination pairs across Canadian provinces (AB, BC, MB, NB, NL, NS, ON, PE, QC, SK, YT) with identical CWT weight breaks.
     - **Table C (Partial Truckload / PTL Flat Rates):** High-density point-to-point flat rates (e.g., Calgary to Mississauga $2,756, Vancouver to Toronto $4,050).

---

## Complete Catalog of 50 Distinct Templates (Training Corpus)

| ID | Format Archetype | Representative Carrier / Standard | Rating Methodology | Key Parser Challenges |
|:---|:---|:---|:---|:---|
| **01** | **Canadian Point-to-Point & Between-Localities Tariff** | Day & Ross (Guide Sheet) | CWT Weight Breaks (MIN, LTL, 1M, 2M, 5M, 10M, 20M) + PTL Flat | 29 textual accessorial clauses, waived items, Marine Atlantic ferry tiers, nested tables |
| **02** | **CzarLite / SMC3 Standard Class-Rate Base Tariff** | SMC3 CzarLite Base | Class 50–500 across standard breaks (L5C, M5C, M1M–M40M) with FAK discount matrix | 3-digit Zip matrix, multiple rate base numbers (RBN), FAK grouping tables |
| **03** | **Canadian Postal Code (FSA) Parcel Matrix** | Purolator Express / Ground | Origin FSA (first 3 chars) to Dest FSA mapped to Zones 1–24; 1–150 lbs weight grid | Two-stage lookup: postal mapping tab + weight/zone pricing grid |
| **04** | **Courier Multiweight / Hundredweight Pricing** | FedEx Ground Multiweight | Aggregate shipment weight (>200 lbs) tiered rates (Tier 1–4) by Zones 2–8 | Minimum average package weight floor (15 lbs), tier thresholds, volume discounting |
| **05** | **Commercial Parcel Incentive Agreement** | UPS Daily Rates & Custom Agreement | List rate grid with separate customer incentive discount % table by service type | Applying variable negative discount multipliers against standard published list |
| **06** | **Eastern/Western Canadian Regional LTL Grid** | Manitoulin Transport | Terminal-to-terminal zone resolution, LTL CWT breaks, northern remote area fee schedule | Remote lane surcharges based on specific postal prefixes; seasonal winter road rules |
| **07** | **Atlantic Canada Regional Density Matrix** | Midland Transport | Atlantic provinces (NB, NS, PE, NL) to ON/QC; cubic foot density minimums (10 lbs/cu ft) | Mandatory density conversion check before rate lookup; heater service percentage fee |
| **08** | **Prairies & West Coast Inter-Provincial Matrix** | Kindersley Transport | Inter-provincial lane pairs (AB/SK/MB/BC), pallet rates vs CWT breaks | Identifying whether shipment bills as pallet position or CWT break; tailgate rules |
| **09** | **Transborder US-Canada Standard LTL Sheet** | TST-CF Express (TFI) | State-to-Province matrix, border clearance fee, in-bond storage fee | Dual-currency (USD/CAD) rules, customs broker notification fee, exchange peg |
| **10** | **Metro Cross-Border Expedited Matrix** | Polaris Transportation | Toronto/Montreal to US Northeast/Midwest metro zones (NY, NJ, IL, OH) | Metro congestion surcharges, hazardous cargo flat tiers, customs bond processing |
| **11** | **Temperature-Controlled Reefer LTL Tariff** | Erb Transport | Heated / Refrigerated / Frozen tiered per-pallet (1–26 positions) | Mandatory temperature range check (+4°C vs -18°C), pre-cool fee, temp logger fee |
| **12** | **Intermodal Rail vs Road Dual-Mode Tariff** | Maritime-Ontario Freight Lines | Dual columns for "Intermodal Rail" vs "Over-The-Road Expedited" | Mode selection based on transit time preference; Marine Atlantic ferry surcharge |
| **13** | **Domestic Rail Intermodal Ramp-to-Ramp Matrix** | CN Rail Domestic Intermodal | Container sizes (40ft, 53ft) ramp origin to ramp dest, rail fuel escalator | Terminal gate reservation fees, storage demurrage per 24 hours, carbon tax item |
| **14** | **Cross-Border Canada-US-Mexico Rail Tariff** | CPKC (Canadian Pacific Kansas City) | Tri-national corridor flat rates, border inspection add-on, drayage connectors | Multi-border transit rules, chassis provisioning fees, currency exchange adjustments |
| **15** | **Pacific Gateway Port Drayage Tariff** | Port of Vancouver Drayage Carriers | Zone 1–6 radius from port terminals, container chassis split, clean truck fee | Free time 90 mins, demurrage per hour, off-dock container storage schedule |
| **16** | **St. Lawrence River Port Drayage Schedule** | Port of Montreal Drayage | Terminal piers to Greater Montreal & Valleyfield zones; inspection fee | Pier congestion surcharge, empty container drop-off fee, night gate surcharge |
| **17** | **International Express Export/Import Tariff** | DHL Express Worldwide | Country Zone 1–10, per 0.5 kg (up to 30 kg) and per 1 kg (31–70 kg) | Chargeable weight (dim 5000 cc/kg), emergency situation fee, remote area per kg |
| **18** | **Government Postal Commercial Contract** | Canada Post Commercial Parcel | Parcel Services (Regular, Expedited, Xpresspost), dim factor 166 (imperial) / 6000 | Density ratio check, national vs regional rate tables, fuel surcharge weekly index |
| **19** | **B2B Regional Small Parcel Courier Grid** | Canpar Express | Ground, Select, Overnight; Postal lookup matrix to 12 zones | Non-conveyable parcel surcharge, residential delivery fee, signature required fee |
| **20** | **Cross-Border LTL Direct Matrix** | Estes Express Lines | Direct US to ON/QC lanes, discount off EXLA base, linear foot rule (1,000 lbs/ft) | Overlength fees (>8ft, >12ft), liftgate delivery schedule, residential notification |
| **21** | **3-Digit Zip Zone-to-Zone LTL Tariff** | Old Dominion Freight Line (ODFL) | 3-digit Zip origin to 3-digit Zip dest, Class 50–100 mapped to FAK brackets | ODFL 559 base tariff reference, guaranteed delivery window upcharge (10:30am / 12pm) |
| **22** | **Regional Southern/Midwestern LTL Tariff** | R+L Carriers | Weight brackets (MC, 100, 500, 1M, 2M, 5M, 10M, 20M, 30M), fuel index DOE | Inside delivery fee, limited access fee, sorting and segregation per piece |
| **23** | **National Multi-Tier FAK LTL Matrix** | TForce Freight / YRC Legacy | Multi-FAK groupings (FAK 50 for 50–85, FAK 70 for 92.5–125) | Identifying FAK mapping column before referencing base rate matrix; minimum floor |
| **24** | **High-Density Metro & Extreme Length LTL** | SAIA LTL Freight | Class matrix with extreme length surcharges (>8ft, >12ft, >16ft, >24ft) | Overlength item dimensions parsing; high-cost delivery metro surcharges (NYC, CHI) |
| **25** | **Flatbed Truckload Per-Mile & Accessorials** | Flatbed Specialized Carriers | Rate per loaded mile via PC*Miler Practical + deadhead allowance | Tarping charges (4ft, 6ft, 8ft drops), coil racks, pipe stakes, layover per day |
| **26** | **Dedicated Contract Carriage Schedule** | Dedicated Fleet Operators | Fixed tractor cost/month + variable driver hourly rate + mileage fuel peg | Multi-component pricing formula: monthly base + hourly driver + per-mile fuel |
| **27** | **Refrigerated Truckload Multi-Drop Matrix** | FTL Reefer Carriers | Point-to-point flat lane rates + multi-stop schedule ($100 1st stop, $150 2nd stop) | Layover fee ($350/day), breakdown detention with power, driver assist unloading |
| **28** | **Heavy Haul & Stepdeck Specialized Schedule** | Oversized Hauling Specialists | Base mileage rate + axle count surcharge (5-axle, 7-axle, 9-axle, 13-axle) | State/provincial wide-load permit pass-through, pilot/escort vehicle per mile |
| **29** | **Ocean FCL Transpacific Rate Sheet** | Ocean Carriers (Transpacific West Coast) | Port-to-Port (Shanghai to Vancouver) for 20ft, 40ft, 40HC, Reefer | Ocean freight + BAF + CAF + GRI + PSS (Peak Season) + Port Security Fee |
| **30** | **Ocean FCL Transatlantic Rate Sheet** | Ocean Carriers (Transatlantic East Coast) | Rotterdam/Antwerp to Montreal/Halifax for 20ft/40ft | Terminal Handling Charge (THC origin & dest), low sulfur surcharge, inland feeder |
| **31** | **Ocean LCL CFS-to-CFS Consolidation Tariff** | Ocean Freight Forwarders | CFS-to-CFS rated on Weight or Measure ($45 per CBM or 1,000 kg, whichever higher) | Calculating CBM vs metric ton volume ratio, deconsolidation fee, customs doc fee |
| **32** | **International Air Freight Chargeable Weight Tariff** | IATA Air Forwarders | Chargeable weight (+45kg, +100kg, +300kg, +500kg, +1000kg) origin airport to dest | IATA 1:6000 ratio check; Fuel Surcharge (FSC) and Security Surcharge (SSC) per kg |
| **33** | **Domestic Airport-to-Airport Air Cargo** | Air Canada Cargo / WestJet Cargo | General Cargo vs Prioritise service levels, minimum shipment charge | Air waybill fee, screening fee, dangerous goods documentation check |
| **34** | **White Glove Final Mile Residential Delivery** | Final Mile Logistics Providers | Tiered service: Threshold, Room of Choice, White Glove / De-trash / Assembly | 2-man delivery minimum, stair carry fee (per flight >2), time-specific delivery window |
| **35** | **Expedited Hot Shot Courier Vehicle Matrix** | Hot Shot / Critical Freight | Vehicle types: Cargo Van, Sprinter, 16ft Straight, 24ft Box Truck, 53ft Team | Per-mile loaded rate, deadhead per mile, driver wait time billed in 15-min increments |
| **36** | **Cross-Border Drayage & Transload Schedule** | Pacific Northwest Transload Facilities | Transload fee per pallet, container drayage to/from marine ramp, cross-dock | Storage free time 7 days, pallet restacking fee, shrink-wrap fee, seal inspection |
| **37** | **Northern Remote & Seasonal Ice Road Tariff** | Northern Canadian Logistics (NWT/Yukon) | Edmonton/Yellowknife seasonal road vs ice road rates, barge connection | Seasonal effective dates (winter road open/close dates), unpaved gravel road fee |
| **38** | **Pallet-Position Pool LTL Matrix** | Regional Pallet Carriers | Flat rate per pallet space (1–12 pallets) up to 1,500 lbs/pallet | Excess weight over 1,500 lbs billed at CWT; CHEP pallet return administration fee |
| **39** | **Volume LTL / Partial Truckload (PTL) Space Grid** | Volume LTL Freight Brokers | Brackets: 10ft, 15ft, 20ft, 25ft, 30ft linear trailer space; max weight caps | Comparing actual weight vs linear foot minimum (1,000 lbs/ft); space guarantee fee |
| **40** | **Trade Show & Event Logistics Schedule** | Exhibition Freight Handlers | Advanced warehouse delivery vs direct-to-convention center delivery | Marshaling yard fee, weekend target check-in fee, empty crate storage fee |
| **41** | **Retail Distribution Center Compliance Schedule** | Big-Box Compliance Logistics | Flat rate + DC compliance fee (Amazon, Walmart, Costco, Target) | Strict delivery window clause, mandatory lumper fee, carton barcode verification |
| **42** | **Hazardous Materials / Dangerous Goods (TDG)** | Specialized Chemical Transport | TDG classes (Class 1–9) surcharge matrix, placarding fee, emergency line | Explosive/Radioactive absolute exclusion; emergency response document charge |
| **43** | **Accessorial-Only Standalone Tariff Sheet** | National LTL Carrier Council | Detailed schedule of all ancillary fees (liftgate, residential, re-weigh, inside) | Pure accessorial rulebook; no base rates — must link to base rate sheet |
| **44** | **Terminal Cross-Dock & In-and-Out Schedule** | 3PL Warehousing Providers | Unload per pallet, reload per pallet, cross-dock consolidation per CWT | Sorting by SKU fee, slip-sheet fee, damaged freight staging per day |
| **45** | **Contract Logistics Storage & Demurrage** | Public & Contract Warehousing | Storage per pallet per month/week, warehouse in/out handling fee | Split month pro-rata rules, minimum monthly billing commitment |
| **46** | **US-Mexico Twin-Plant (Maquiladora) Transfer** | Cross-Border Mexico Freight | Laredo/El Paso bridge drayage, Mexican transfer carrier fee, customs broker | Border crossing document fee, Mexican VAT (IVA) exemption conditions |
| **47** | **Automotive JIT Milk-Run Route Matrix** | Automotive Logistics | Fixed route rate per loop, sequence delivery window compliance fee | Penalties for delay billed per minute; dedicated rack return fee |
| **48** | **Oversize Parcel & Non-Conveyable Package Grid** | Regional Courier Services | Base parcel rate + Over Maximum Limits fee, Non-Conveyable surcharge | Dimensional length + girth > 130 in check; cylindrical packaging surcharge |
| **49** | **High-Value Armored & Escort Cargo Tariff** | High-Security Logistics | Declared valuation per $100 value above carrier liability, GPS monitoring | Dual-driver armed team rate, continuous satellite tracking ping fee |
| **50** | **Metropolitan Same-Day Courier Radial Distance Grid** | Same-Day City Messengers | Concentric radial zones (0–10 km, 10–25 km, 25–50 km), vehicle tiers (car, van) | Speed tiers: Direct 60 min, Rush 2 hr, Same-Day 4 hr; after-hours multiplier |

---

## Technical Integration into RateSift Architecture

### 1. Ingestion Pipeline & Layout Classification Heuristic
Before parsing, the Sheet Inspector classifies the workbook layout into one of 7 meta-categories:
1. **P2P_CWT_MATRIX** (e.g., Template 01, 06, 07, 08): Origin, Dest, Min, LTL, CWT breaks.
2. **CZARLITE_SMC3** (e.g., Template 02, 21, 23): 3-digit Zip matrix with Class and FAK discount table.
3. **POSTAL_ZONE_GRID** (e.g., Template 03, 05, 18, 19): FSA/Zip lookup to Zone, then Zone-to-Weight grid.
4. **PER_MILE_ACCESSORIAL** (e.g., Template 25, 26, 35): Mileage bands/rates + accessorial add-on sheet.
5. **PALLET_SPACE_TIER** (e.g., Template 11, 27, 38, 39): Pallet count / linear footage brackets.
6. **INTERMODAL_DRAYAGE** (e.g., Template 13, 14, 15, 16): Ramp/Pier to zone flat rates + detention.
7. **INTERNATIONAL_WM** (e.g., Template 29, 30, 31, 32): Port-to-port container or W/M CBM pricing.

### 2. Multi-Table and Footnote Parser Execution (Rules 3 & 4)
- **Cell Traceability:** In every template, extracted numbers store the coordinate (e.g., `Day_Ross_2024.xlsx!Terms!C14` or `Purolator_2026.xlsx!Zone_Grid!D22`).
- **Footnote Harvester:** Text paragraphs following tables (like Day & Ross rows 18-29) are parsed with a condition-action extractor to harvest conditional accessorials, exceptions (Costco/Walmart/Amazon), and ferry surcharges.

### 3. Automated Training & Verification Harness
A dedicated test suite runs all 50 template formats through the extractor:
- Confirms zero guessing on missing cells (Rule 1).
- Normalizes into the uniform schema (Rule 2).
- Validates 100% deterministic calculation (Rule 8).
