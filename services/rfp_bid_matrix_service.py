"""
services/rfp_bid_matrix_service.py
==================================
1-Click Shipper RFP / Multi-Lane CWT Bid Matrix Generator.

Allows a freight broker to submit 1 to 50 Origin-Destination lanes at once and generates:
1. A clean Shipper-Facing Multi-Lane Bid Matrix across standard Canadian LTL weight breaks
   (MIN, L5C, M5C, M1M, M2M, M5M) with the broker's % markup and minimum dollar profit floor applied
   (strictly hiding internal carrier names and wholesale costs).
2. An Internal Broker Award Cheat-Sheet recording the lowest-cost winning carrier, wholesale cost,
   broker margin ($ CAD), and exact Excel source cell coordinate for every lane and weight bracket.
"""

from typing import Any, Dict, List, Optional
from services.quotelytics_engine import quote_all_confirmed_carriers

STANDARD_RFP_BRACKETS = [
    {"bracket": "MIN (150 lbs)", "test_weight_lbs": 150.0, "skids": 1},
    {"bracket": "L5C (350 lbs)", "test_weight_lbs": 350.0, "skids": 1},
    {"bracket": "M5C (750 lbs)", "test_weight_lbs": 750.0, "skids": 1},
    {"bracket": "M1M (1,500 lbs)", "test_weight_lbs": 1500.0, "skids": 2},
    {"bracket": "M2M (3,000 lbs)", "test_weight_lbs": 3000.0, "skids": 3},
    {"bracket": "M5M (6,000 lbs)", "test_weight_lbs": 6000.0, "skids": 6},
]


def generate_shipper_rfp_bid_matrix(
    user_id: str,
    lanes: List[Dict[str, str]],
    markup_pct: float = 15.0,
    min_margin_dollars: float = 45.0,
    brackets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Evaluates all confirmed tenant carrier tariffs across every requested lane and weight bracket,
    producing both a Shipper-Facing Bid Matrix and an Internal Broker Award Cheat-Sheet.
    """
    if not lanes:
        raise ValueError("Please provide at least one origin-destination lane for the RFP bid matrix.")

    active_brackets = brackets or STANDARD_RFP_BRACKETS
    mk_mult = 1.0 + (max(0.0, float(markup_pct or 0.0)) / 100.0)
    min_floor = max(0.0, float(min_margin_dollars or 0.0))

    shipper_matrix_rows: List[Dict[str, Any]] = []
    internal_award_rows: List[Dict[str, Any]] = []

    for lane in lanes[:50]:
        orig = str(lane.get("origin") or "").strip()
        dest = str(lane.get("destination") or "").strip()
        if not orig or not dest:
            continue

        shipper_row: Dict[str, Any] = {
            "origin": orig,
            "destination": dest,
            "brackets": {},
        }
        internal_row: Dict[str, Any] = {
            "origin": orig,
            "destination": dest,
            "awards": {},
        }

        for b in active_brackets:
            b_name = b["bracket"]
            wt = float(b["test_weight_lbs"])
            skids = int(b.get("skids") or 1)

            try:
                res = quote_all_confirmed_carriers(
                    user_id=user_id,
                    origin=orig,
                    destination=dest,
                    actual_weight=wt,
                    skid_count=skids,
                )
                quotes = res.get("quotes") or []
            except Exception:
                quotes = []

            if quotes:
                best = quotes[0]
                wholesale = round(float(best.get("final_total") or 0.0), 2)
                pct_sell = round(wholesale * mk_mult, 2)
                floor_sell = round(wholesale + min_floor, 2)
                client_sell = max(pct_sell, floor_sell)
                margin = round(client_sell - wholesale, 2)

                shipper_row["brackets"][b_name] = {
                    "quoted_rate_cad": client_sell,
                    "transit_days": best.get("transit_days") or 3,
                }
                internal_row["awards"][b_name] = {
                    "winning_carrier": best.get("carrier_name"),
                    "wholesale_cost_cad": wholesale,
                    "client_sell_cad": client_sell,
                    "broker_margin_cad": margin,
                    "source_coordinate": best.get("source_coordinate") or best.get("source_cell") or "",
                }
            else:
                shipper_row["brackets"][b_name] = None
                internal_row["awards"][b_name] = None

        shipper_matrix_rows.append(shipper_row)
        internal_award_rows.append(internal_row)

    return {
        "status": "success",
        "total_lanes": len(shipper_matrix_rows),
        "markup_pct": float(markup_pct),
        "min_margin_dollars": min_floor,
        "brackets": [b["bracket"] for b in active_brackets],
        "shipper_bid_matrix": shipper_matrix_rows,
        "internal_award_cheat_sheet": internal_award_rows,
    }
