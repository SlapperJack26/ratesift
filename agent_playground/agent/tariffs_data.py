"""
Embedded Tariff Corpus for Agent Playground
Contains confirmed tariffs including Day & Ross Guide #1, Purolator Parcel, and Maritime Intermodal.
Enables completely standalone rating without external database dependencies.
"""
from typing import List, Dict, Any

# Day & Ross Canadian LTL / PTL Tariff (Guide Template #1 Calibration Standard)
DAY_AND_ROSS_TARIFF: Dict[str, Any] = {
    "sheet_id": "guide-day-ross-001",
    "carrier_name": "Day & Ross LTL",
    "service_type": "Standard LTL Freight",
    "currency": "CAD",
    "weight_unit": "lb",
    "dim_divisor": 139.0,
    "effective_date": "2026-01-01",
    "expiry_date": "2027-12-31",
    "fuel_surcharge_pct": 28.5,
    "minimum_charges": [
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_charge": 225.00, "source": "DayRoss_Tariff!E12"},
        {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "min_charge": 145.00, "source": "DayRoss_Tariff!E13"},
        {"origin": "*", "destination": "*", "min_charge": 165.00, "source": "DayRoss_Tariff!E10"}
    ],
    "breaks": [
        # Calgary -> Lindsay (Lane 1)
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_w": 0, "max_w": 499, "rate": 48.50, "rate_type": "CWT", "transit_days": 4, "source": "DayRoss_Tariff!C22"},
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_w": 500, "max_w": 999, "rate": 39.75, "rate_type": "CWT", "transit_days": 4, "source": "DayRoss_Tariff!D22"},
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_w": 1000, "max_w": 1999, "rate": 31.20, "rate_type": "CWT", "transit_days": 4, "source": "DayRoss_Tariff!E22"},
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_w": 2000, "max_w": 4999, "rate": 26.40, "rate_type": "CWT", "transit_days": 4, "source": "DayRoss_Tariff!F22"},
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_w": 5000, "max_w": 99999, "rate": 21.10, "rate_type": "CWT", "transit_days": 4, "source": "DayRoss_Tariff!G22"},

        # Toronto -> Montreal (Lane 2)
        {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "min_w": 0, "max_w": 499, "rate": 24.50, "rate_type": "CWT", "transit_days": 1, "source": "DayRoss_Tariff!C25"},
        {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "min_w": 500, "max_w": 999, "rate": 19.80, "rate_type": "CWT", "transit_days": 1, "source": "DayRoss_Tariff!D25"},
        {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "min_w": 1000, "max_w": 1999, "rate": 15.60, "rate_type": "CWT", "transit_days": 1, "source": "DayRoss_Tariff!E25"},
        {"origin": "TORONTO, ON", "destination": "MONTREAL, QC", "min_w": 2000, "max_w": 99999, "rate": 12.30, "rate_type": "CWT", "transit_days": 1, "source": "DayRoss_Tariff!F25"},

        # Default Canada-wide LTL fallback bracket
        {"origin": "*", "destination": "*", "min_w": 0, "max_w": 499, "rate": 35.00, "rate_type": "CWT", "transit_days": 3, "source": "DayRoss_Tariff!C99"},
        {"origin": "*", "destination": "*", "min_w": 500, "max_w": 999, "rate": 29.00, "rate_type": "CWT", "transit_days": 3, "source": "DayRoss_Tariff!D99"},
        {"origin": "*", "destination": "*", "min_w": 1000, "max_w": 99999, "rate": 22.00, "rate_type": "CWT", "transit_days": 3, "source": "DayRoss_Tariff!E99"}
    ],
    "accessorials": {
        "liftgate": {"name": "Power Tailgate / Liftgate", "type": "FLAT", "amount": 75.00, "source": "DayRoss_Tariff!Term_12"},
        "appointment": {"name": "Delivery Appointment / Notify", "type": "FLAT", "amount": 35.00, "source": "DayRoss_Tariff!Term_08"},
        "heated": {"name": "Protect from Freeze (Heated)", "type": "PERCENTAGE", "amount": 15.0, "min_fee": 45.00, "source": "DayRoss_Tariff!Term_19"},
        "dangerous_goods": {"name": "Dangerous Goods / Hazmat", "type": "FLAT", "amount": 85.00, "source": "DayRoss_Tariff!Term_05"},
        "residential": {"name": "Residential Delivery", "type": "FLAT", "amount": 65.00, "source": "DayRoss_Tariff!Term_14"},
        "residential_pickup": {"name": "Residential Pickup", "type": "FLAT", "amount": 65.00, "source": "DayRoss_Tariff!Term_15"},
        "inside_delivery": {"name": "Inside Delivery", "type": "FLAT", "amount": 50.00, "source": "DayRoss_Tariff!Term_11"},
        "after_hours": {"name": "After Hours Delivery", "type": "FLAT", "amount": 90.00, "source": "DayRoss_Tariff!Term_03"}
    }
}

# Purolator Parcel Express Tariff (Rule 18 limit: max 150 lbs)
PUROLATOR_PARCEL_TARIFF: Dict[str, Any] = {
    "sheet_id": "guide-purolator-002",
    "carrier_name": "Purolator Express",
    "service_type": "Ground Parcel",
    "currency": "CAD",
    "weight_unit": "lb",
    "dim_divisor": 139.0,
    "max_weight_limit": 150.0,
    "effective_date": "2026-01-01",
    "expiry_date": "2027-12-31",
    "fuel_surcharge_pct": 21.0,
    "minimum_charges": [
        {"origin": "*", "destination": "*", "min_charge": 22.50, "source": "Puro_Guide!A1"}
    ],
    "breaks": [
        {"origin": "TORONTO, ON", "destination": "OTTAWA, ON", "min_w": 0, "max_w": 10, "rate": 18.50, "rate_type": "FLAT", "transit_days": 1, "source": "Puro_Guide!C4"},
        {"origin": "TORONTO, ON", "destination": "OTTAWA, ON", "min_w": 11, "max_w": 50, "rate": 34.20, "rate_type": "FLAT", "transit_days": 1, "source": "Puro_Guide!C5"},
        {"origin": "TORONTO, ON", "destination": "OTTAWA, ON", "min_w": 51, "max_w": 150, "rate": 58.00, "rate_type": "FLAT", "transit_days": 1, "source": "Puro_Guide!C6"},
        {"origin": "*", "destination": "*", "min_w": 0, "max_w": 50, "rate": 39.00, "rate_type": "FLAT", "transit_days": 2, "source": "Puro_Guide!D5"},
        {"origin": "*", "destination": "*", "min_w": 51, "max_w": 150, "rate": 69.00, "rate_type": "FLAT", "transit_days": 2, "source": "Puro_Guide!D6"}
    ],
    "accessorials": {
        "residential": {"name": "Residential Surcharge", "type": "FLAT", "amount": 6.50, "source": "Puro_Guide!Fee_Res"},
        "appointment": {"name": "Signature Required", "type": "FLAT", "amount": 5.00, "source": "Puro_Guide!Fee_Sig"}
    }
}

# Maritime-Ontario Intermodal Rail Tariff (Eco & Value Freight)
INTERMODAL_RAIL_TARIFF: Dict[str, Any] = {
    "sheet_id": "guide-rail-003",
    "carrier_name": "Canadian Intermodal Rail",
    "service_type": "Economy Rail / PTL",
    "currency": "CAD",
    "weight_unit": "lb",
    "dim_divisor": 139.0,
    "min_weight_limit": 500.0,
    "effective_date": "2026-01-01",
    "expiry_date": "2027-12-31",
    "fuel_surcharge_pct": 24.0,
    "minimum_charges": [
        {"origin": "*", "destination": "*", "min_charge": 290.00, "source": "Rail_Tariff!Min"}
    ],
    "breaks": [
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_w": 500, "max_w": 1999, "rate": 24.80, "rate_type": "CWT", "transit_days": 7, "source": "Rail_Tariff!C12"},
        {"origin": "CALGARY, AB", "destination": "LINDSAY, ON", "min_w": 2000, "max_w": 99999, "rate": 18.50, "rate_type": "CWT", "transit_days": 7, "source": "Rail_Tariff!D12"},
        {"origin": "*", "destination": "*", "min_w": 500, "max_w": 99999, "rate": 20.00, "rate_type": "CWT", "transit_days": 6, "source": "Rail_Tariff!E10"}
    ],
    "accessorials": {
        "liftgate": {"name": "Terminal Liftgate", "type": "FLAT", "amount": 80.00, "source": "Rail_Tariff!Term_01"},
        "heated": {"name": "Heated Railcar", "type": "PERCENTAGE", "amount": 12.0, "min_fee": 60.00, "source": "Rail_Tariff!Term_02"}
    }
}

AVAILABLE_TARIFFS = [
    DAY_AND_ROSS_TARIFF,
    PUROLATOR_PARCEL_TARIFF,
    INTERMODAL_RAIL_TARIFF
]
