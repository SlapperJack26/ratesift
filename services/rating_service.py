import random
from typing import Dict, Any, List

CARRIERS = [
    {"name": "FedEx", "service": "FedEx Priority Freight", "base_per_lb": 1.45, "min_charge": 45.00},
    {"name": "UPS", "service": "UPS Worldwide Saver", "base_per_lb": 1.60, "min_charge": 52.00},
    {"name": "Estes Express", "service": "Estes Standard LTL", "base_per_lb": 0.55, "min_charge": 110.00},
    {"name": "USPS", "service": "USPS Priority Commercial", "base_per_lb": 1.20, "min_charge": 18.50},
    {"name": "R+L Carriers", "service": "R+L Guaranteed Morning", "base_per_lb": 0.85, "min_charge": 125.00}
]

def calculate_quote_rate(origin_zip: str, dest_zip: str, weight_lbs: float, markup_pct: float = 10.0) -> Dict[str, Any]:
    """
    Calculates batch shipping quote rates strictly for quotation purposes.
    Applies mileage/zone multiplier and broker markup percentage.
    No booking, no labels, no tracking.
    """
    # Zone estimation based on first digit differential
    try:
        o_first = int(origin_zip[:1]) if origin_zip else 9
        d_first = int(dest_zip[:1]) if dest_zip else 1
        zone_diff = abs(o_first - d_first)
    except Exception:
        zone_diff = 4
        
    distance_multiplier = 1.0 + (zone_diff * 0.12)
    
    # Select best carrier based on weight class
    if weight_lbs > 150:
        # LTL Carrier preferred
        carrier_choice = CARRIERS[2] if zone_diff < 5 else CARRIERS[4]
    else:
        # Parcel / Air Carrier preferred
        carrier_choice = CARRIERS[0] if zone_diff % 2 == 0 else CARRIERS[1]
        
    base_calc = max(carrier_choice["min_charge"], weight_lbs * carrier_choice["base_per_lb"] * distance_multiplier)
    base_rate = round(base_calc, 2)
    
    # Calculate Markup
    markup_multiplier = 1.0 + (markup_pct / 100.0)
    final_rate = round(base_rate * markup_multiplier, 2)
    
    return {
        "carrier": carrier_choice["name"],
        "service": carrier_choice["service"],
        "base_rate": base_rate,
        "markup_pct": markup_pct,
        "final_rate": final_rate
    }

def calculate_batch_quotes(parsed_rows: List[Dict[str, Any]], markup_pct: float = 10.0) -> List[Dict[str, Any]]:
    """
    Processes all parsed rows into formal quote line items.
    """
    import time
    quoted_items = []
    ts_seed = int(time.time()) % 100000
    for idx, row in enumerate(parsed_rows):
        quote_id = f"SF-{ts_seed}{idx:02d}"
        rate_info = calculate_quote_rate(
            origin_zip=row["origin_zip"],
            dest_zip=row["dest_zip"],
            weight_lbs=row["weight_lbs"],
            markup_pct=markup_pct
        )
        
        quoted_items.append({
            "quote_id": quote_id,
            "row_num": row["row_num"],
            "origin_zip": row["origin_zip"],
            "dest_zip": row["dest_zip"],
            "weight_lbs": row["weight_lbs"],
            "carrier": rate_info["carrier"],
            "service": rate_info["service"],
            "base_rate": rate_info["base_rate"],
            "markup_pct": rate_info["markup_pct"],
            "final_rate": rate_info["final_rate"],
            "coordinate": row["coordinate"]
        })
        
    return quoted_items
