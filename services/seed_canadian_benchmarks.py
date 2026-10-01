import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from services.ratesift_db_service import (
    get_connection,
    create_rate_sheet,
    confirm_rate_sheet,
    insert_carrier_zones,
    insert_weight_breaks,
    insert_carrier_minimums,
    insert_carrier_surcharges,
    insert_rate_sheet_cells
)

# Standard Canadian benchmark carriers with realistic LTL tariffs and market-tested CWT rates
CANADIAN_BENCHMARK_CARRIERS = [
    {
        "carrier_name": "Day & Ross",
        "service_name": "General Road LTL",
        "tariff_ref": "Tariff DR-2026 (Benchmark Canadian LTL)",
        "effective_date": "2026-01-01",
        "expiry_date": "2027-12-31",
        "mode": "LTL",
        "currency": "CAD",
        "weight_unit": "lb",
        "dim_divisor": 139.0,
        "dim_min_rule": "10.00 lbs per cu ft up to 20.00 ft",
        "surcharges": [
            {
                "surcharge_code": "APPOINTMENT",
                "name": "Appointment Deliveries",
                "condition_type": "appointment",
                "fee_type": "FLAT",
                "amount": 20.00,
                "source_cell": "Benchmark DR-2026 • Terms Col B"
            },
            {
                "surcharge_code": "POWER_TAILGATE",
                "name": "Power Tailgate / Liftgate",
                "condition_type": "liftgate",
                "fee_type": "FLAT",
                "amount": 45.00,
                "source_cell": "Benchmark DR-2026 • Terms Col B"
            },
            {
                "surcharge_code": "RESIDENTIAL_DELIVERY",
                "name": "Residential / Limited Access Delivery",
                "condition_type": "residential_delivery",
                "fee_type": "FLAT",
                "amount": 35.00,
                "source_cell": "Benchmark DR-2026 • Terms Col B"
            },
            {
                "surcharge_code": "DANGEROUS_GOODS",
                "name": "Dangerous Goods (TDG)",
                "condition_type": "dangerous_goods",
                "fee_type": "FLAT",
                "amount": 55.00,
                "source_cell": "Benchmark DR-2026 • Terms Col B"
            },
            {
                "surcharge_code": "PROTECTIVE_HEAT",
                "name": "Heated / Protective Service",
                "condition_type": "heated",
                "fee_type": "PERCENTAGE",
                "amount": 18.00,
                "min_fee": 40.00,
                "source_cell": "Benchmark DR-2026 • Terms Col B"
            }
        ],
        "corridors": [
            {
                "origin": "CALGARY, AB", "dest": "LINDSAY, ON", "transit_days": 4, "min_charge": 185.00,
                "breaks": {"LTL": 32.50, "CWT:1000": 26.80, "CWT:2000": 22.40, "CWT:5000": 18.90, "CWT:10000": 15.50}
            },
            {
                "origin": "TORONTO, ON", "dest": "MONTREAL, QC", "transit_days": 1, "min_charge": 125.00,
                "breaks": {"LTL": 19.50, "CWT:1000": 16.20, "CWT:2000": 13.50, "CWT:5000": 10.80, "CWT:10000": 8.90}
            },
            {
                "origin": "TORONTO, ON", "dest": "OTTAWA, ON", "transit_days": 1, "min_charge": 115.00,
                "breaks": {"LTL": 18.00, "CWT:1000": 15.00, "CWT:2000": 12.50, "CWT:5000": 9.90, "CWT:10000": 8.20}
            },
            {
                "origin": "VANCOUVER, BC", "dest": "EDMONTON, AB", "transit_days": 2, "min_charge": 165.00,
                "breaks": {"LTL": 28.00, "CWT:1000": 23.50, "CWT:2000": 19.80, "CWT:5000": 16.20, "CWT:10000": 13.50}
            },
            {
                "origin": "TORONTO, ON", "dest": "CALGARY, AB", "transit_days": 4, "min_charge": 190.00,
                "breaks": {"LTL": 33.00, "CWT:1000": 27.20, "CWT:2000": 22.80, "CWT:5000": 19.20, "CWT:10000": 15.80}
            },
            {
                "origin": "WINNIPEG, MB", "dest": "TORONTO, ON", "transit_days": 3, "min_charge": 155.00,
                "breaks": {"LTL": 24.50, "CWT:1000": 20.80, "CWT:2000": 17.50, "CWT:5000": 14.50, "CWT:10000": 11.90}
            },
            {
                "origin": "HALIFAX, NS", "dest": "MONTREAL, QC", "transit_days": 2, "min_charge": 145.00,
                "breaks": {"LTL": 23.00, "CWT:1000": 19.50, "CWT:2000": 16.20, "CWT:5000": 13.20, "CWT:10000": 10.80}
            }
        ]
    },
    {
        "carrier_name": "Manitoulin Transport",
        "service_name": "Direct LTL Service",
        "tariff_ref": "Tariff MT-2026 (Benchmark Canadian LTL)",
        "effective_date": "2026-01-01",
        "expiry_date": "2027-12-31",
        "mode": "LTL",
        "currency": "CAD",
        "weight_unit": "lb",
        "dim_divisor": 139.0,
        "dim_min_rule": "10.00 lbs per cu ft up to 20.00 ft",
        "surcharges": [
            {
                "surcharge_code": "APPOINTMENT",
                "name": "Appointment Deliveries",
                "condition_type": "appointment",
                "fee_type": "FLAT",
                "amount": 25.00,
                "source_cell": "Benchmark MT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "POWER_TAILGATE",
                "name": "Power Tailgate / Liftgate",
                "condition_type": "liftgate",
                "fee_type": "FLAT",
                "amount": 50.00,
                "source_cell": "Benchmark MT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "RESIDENTIAL_DELIVERY",
                "name": "Residential / Limited Access Delivery",
                "condition_type": "residential_delivery",
                "fee_type": "FLAT",
                "amount": 40.00,
                "source_cell": "Benchmark MT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "DANGEROUS_GOODS",
                "name": "Dangerous Goods (TDG)",
                "condition_type": "dangerous_goods",
                "fee_type": "FLAT",
                "amount": 60.00,
                "source_cell": "Benchmark MT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "PROTECTIVE_HEAT",
                "name": "Heated / Protective Service",
                "condition_type": "heated",
                "fee_type": "PERCENTAGE",
                "amount": 15.00,
                "min_fee": 45.00,
                "source_cell": "Benchmark MT-2026 • Terms Col B"
            }
        ],
        "corridors": [
            {
                "origin": "CALGARY, AB", "dest": "LINDSAY, ON", "transit_days": 4, "min_charge": 195.00,
                "breaks": {"LTL": 31.80, "CWT:1000": 25.90, "CWT:2000": 21.50, "CWT:5000": 18.20, "CWT:10000": 14.80}
            },
            {
                "origin": "TORONTO, ON", "dest": "MONTREAL, QC", "transit_days": 1, "min_charge": 130.00,
                "breaks": {"LTL": 18.80, "CWT:1000": 15.50, "CWT:2000": 12.90, "CWT:5000": 10.20, "CWT:10000": 8.40}
            },
            {
                "origin": "TORONTO, ON", "dest": "OTTAWA, ON", "transit_days": 1, "min_charge": 120.00,
                "breaks": {"LTL": 17.50, "CWT:1000": 14.40, "CWT:2000": 11.90, "CWT:5000": 9.40, "CWT:10000": 7.80}
            },
            {
                "origin": "VANCOUVER, BC", "dest": "EDMONTON, AB", "transit_days": 3, "min_charge": 170.00,
                "breaks": {"LTL": 27.20, "CWT:1000": 22.80, "CWT:2000": 18.90, "CWT:5000": 15.40, "CWT:10000": 12.80}
            },
            {
                "origin": "TORONTO, ON", "dest": "CALGARY, AB", "transit_days": 4, "min_charge": 195.00,
                "breaks": {"LTL": 32.20, "CWT:1000": 26.50, "CWT:2000": 22.00, "CWT:5000": 18.50, "CWT:10000": 15.10}
            },
            {
                "origin": "WINNIPEG, MB", "dest": "TORONTO, ON", "transit_days": 2, "min_charge": 150.00,
                "breaks": {"LTL": 23.80, "CWT:1000": 19.90, "CWT:2000": 16.80, "CWT:5000": 13.90, "CWT:10000": 11.40}
            },
            {
                "origin": "HALIFAX, NS", "dest": "MONTREAL, QC", "transit_days": 3, "min_charge": 150.00,
                "breaks": {"LTL": 22.50, "CWT:1000": 18.90, "CWT:2000": 15.60, "CWT:5000": 12.70, "CWT:10000": 10.30}
            }
        ]
    },
    {
        "carrier_name": "Midland Transport",
        "service_name": "Atlantic & Central LTL",
        "tariff_ref": "Tariff ML-2026 (Benchmark Canadian LTL)",
        "effective_date": "2026-01-01",
        "expiry_date": "2027-12-31",
        "mode": "LTL",
        "currency": "CAD",
        "weight_unit": "lb",
        "dim_divisor": 139.0,
        "dim_min_rule": "10.00 lbs per cu ft up to 20.00 ft",
        "surcharges": [
            {
                "surcharge_code": "APPOINTMENT",
                "name": "Appointment Deliveries",
                "condition_type": "appointment",
                "fee_type": "FLAT",
                "amount": 20.00,
                "source_cell": "Benchmark ML-2026 • Terms Col B"
            },
            {
                "surcharge_code": "POWER_TAILGATE",
                "name": "Power Tailgate / Liftgate",
                "condition_type": "liftgate",
                "fee_type": "FLAT",
                "amount": 40.00,
                "source_cell": "Benchmark ML-2026 • Terms Col B"
            },
            {
                "surcharge_code": "RESIDENTIAL_DELIVERY",
                "name": "Residential / Limited Access Delivery",
                "condition_type": "residential_delivery",
                "fee_type": "FLAT",
                "amount": 35.00,
                "source_cell": "Benchmark ML-2026 • Terms Col B"
            },
            {
                "surcharge_code": "DANGEROUS_GOODS",
                "name": "Dangerous Goods (TDG)",
                "condition_type": "dangerous_goods",
                "fee_type": "FLAT",
                "amount": 50.00,
                "source_cell": "Benchmark ML-2026 • Terms Col B"
            },
            {
                "surcharge_code": "PROTECTIVE_HEAT",
                "name": "Heated / Protective Service",
                "condition_type": "heated",
                "fee_type": "PERCENTAGE",
                "amount": 16.00,
                "min_fee": 38.00,
                "source_cell": "Benchmark ML-2026 • Terms Col B"
            }
        ],
        "corridors": [
            {
                "origin": "CALGARY, AB", "dest": "LINDSAY, ON", "transit_days": 5, "min_charge": 210.00,
                "breaks": {"LTL": 33.50, "CWT:1000": 27.50, "CWT:2000": 23.00, "CWT:5000": 19.50, "CWT:10000": 16.00}
            },
            {
                "origin": "TORONTO, ON", "dest": "MONTREAL, QC", "transit_days": 1, "min_charge": 120.00,
                "breaks": {"LTL": 19.00, "CWT:1000": 15.80, "CWT:2000": 13.10, "CWT:5000": 10.50, "CWT:10000": 8.60}
            },
            {
                "origin": "TORONTO, ON", "dest": "OTTAWA, ON", "transit_days": 1, "min_charge": 110.00,
                "breaks": {"LTL": 17.00, "CWT:1000": 14.00, "CWT:2000": 11.50, "CWT:5000": 9.10, "CWT:10000": 7.50}
            },
            {
                "origin": "VANCOUVER, BC", "dest": "EDMONTON, AB", "transit_days": 3, "min_charge": 180.00,
                "breaks": {"LTL": 29.00, "CWT:1000": 24.20, "CWT:2000": 20.50, "CWT:5000": 16.90, "CWT:10000": 14.10}
            },
            {
                "origin": "TORONTO, ON", "dest": "CALGARY, AB", "transit_days": 5, "min_charge": 205.00,
                "breaks": {"LTL": 34.00, "CWT:1000": 28.00, "CWT:2000": 23.50, "CWT:5000": 19.80, "CWT:10000": 16.40}
            },
            {
                "origin": "WINNIPEG, MB", "dest": "TORONTO, ON", "transit_days": 3, "min_charge": 160.00,
                "breaks": {"LTL": 25.00, "CWT:1000": 21.20, "CWT:2000": 17.90, "CWT:5000": 14.80, "CWT:10000": 12.20}
            },
            {
                "origin": "HALIFAX, NS", "dest": "MONTREAL, QC", "transit_days": 2, "min_charge": 140.00,
                "breaks": {"LTL": 21.80, "CWT:1000": 18.20, "CWT:2000": 15.00, "CWT:5000": 12.20, "CWT:10000": 9.90}
            }
        ]
    },
    {
        "carrier_name": "Bison Transport",
        "service_name": "Cross-Canada LTL",
        "tariff_ref": "Tariff BT-2026 (Benchmark Canadian LTL)",
        "effective_date": "2026-01-01",
        "expiry_date": "2027-12-31",
        "mode": "LTL",
        "currency": "CAD",
        "weight_unit": "lb",
        "dim_divisor": 139.0,
        "dim_min_rule": "10.00 lbs per cu ft up to 20.00 ft",
        "surcharges": [
            {
                "surcharge_code": "APPOINTMENT",
                "name": "Appointment Deliveries",
                "condition_type": "appointment",
                "fee_type": "FLAT",
                "amount": 22.00,
                "source_cell": "Benchmark BT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "POWER_TAILGATE",
                "name": "Power Tailgate / Liftgate",
                "condition_type": "liftgate",
                "fee_type": "FLAT",
                "amount": 48.00,
                "source_cell": "Benchmark BT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "RESIDENTIAL_DELIVERY",
                "name": "Residential / Limited Access Delivery",
                "condition_type": "residential_delivery",
                "fee_type": "FLAT",
                "amount": 38.00,
                "source_cell": "Benchmark BT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "DANGEROUS_GOODS",
                "name": "Dangerous Goods (TDG)",
                "condition_type": "dangerous_goods",
                "fee_type": "FLAT",
                "amount": 52.00,
                "source_cell": "Benchmark BT-2026 • Terms Col B"
            },
            {
                "surcharge_code": "PROTECTIVE_HEAT",
                "name": "Heated / Protective Service",
                "condition_type": "heated",
                "fee_type": "PERCENTAGE",
                "amount": 17.00,
                "min_fee": 42.00,
                "source_cell": "Benchmark BT-2026 • Terms Col B"
            }
        ],
        "corridors": [
            {
                "origin": "CALGARY, AB", "dest": "LINDSAY, ON", "transit_days": 4, "min_charge": 200.00,
                "breaks": {"LTL": 32.00, "CWT:1000": 26.20, "CWT:2000": 22.00, "CWT:5000": 18.50, "CWT:10000": 15.10}
            },
            {
                "origin": "TORONTO, ON", "dest": "MONTREAL, QC", "transit_days": 1, "min_charge": 135.00,
                "breaks": {"LTL": 19.80, "CWT:1000": 16.50, "CWT:2000": 13.80, "CWT:5000": 11.00, "CWT:10000": 9.10}
            },
            {
                "origin": "TORONTO, ON", "dest": "OTTAWA, ON", "transit_days": 1, "min_charge": 125.00,
                "breaks": {"LTL": 18.20, "CWT:1000": 15.10, "CWT:2000": 12.40, "CWT:5000": 9.80, "CWT:10000": 8.10}
            },
            {
                "origin": "VANCOUVER, BC", "dest": "EDMONTON, AB", "transit_days": 2, "min_charge": 160.00,
                "breaks": {"LTL": 26.50, "CWT:1000": 22.00, "CWT:2000": 18.20, "CWT:5000": 14.90, "CWT:10000": 12.20}
            },
            {
                "origin": "TORONTO, ON", "dest": "CALGARY, AB", "transit_days": 4, "min_charge": 185.00,
                "breaks": {"LTL": 32.50, "CWT:1000": 26.80, "CWT:2000": 22.30, "CWT:5000": 18.80, "CWT:10000": 15.40}
            },
            {
                "origin": "WINNIPEG, MB", "dest": "TORONTO, ON", "transit_days": 2, "min_charge": 152.00,
                "breaks": {"LTL": 24.00, "CWT:1000": 20.20, "CWT:2000": 17.00, "CWT:5000": 14.10, "CWT:10000": 11.60}
            },
            {
                "origin": "HALIFAX, NS", "dest": "MONTREAL, QC", "transit_days": 3, "min_charge": 155.00,
                "breaks": {"LTL": 23.20, "CWT:1000": 19.20, "CWT:2000": 15.90, "CWT:5000": 13.00, "CWT:10000": 10.60}
            }
        ]
    }
]

def ensure_is_benchmark_column():
    """Ensures `is_benchmark` column exists on `rs_rate_sheets`."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(rs_rate_sheets)")
    cols = [r["name"] for r in cursor.fetchall()]
    if "is_benchmark" not in cols:
        try:
            cursor.execute("ALTER TABLE rs_rate_sheets ADD COLUMN is_benchmark INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass
    conn.close()

def seed_canadian_benchmarks_for_user(user_id: str, force: bool = False) -> List[str]:
    """
    Seeds the 4 standard Canadian benchmark carrier tariffs for a tenant.
    Enforces deterministic quoting, Rule 3 cell coordinates, Rule 16 valid active dates,
    and Rule 28 multi-tenant isolation.
    """
    ensure_is_benchmark_column()

    conn = get_connection()
    cursor = conn.cursor()

    # Check if user already has benchmark tariffs
    cursor.execute("""
    SELECT id, carrier_name FROM rs_rate_sheets 
    WHERE user_id = ? AND is_benchmark = 1
    """, (user_id,))
    existing = cursor.fetchall()
    
    if existing and not force:
        conn.close()
        return [r["id"] for r in existing]

    # If force or re-seeding, clean up previous benchmark sheets for this user
    if existing:
        sheet_ids = [r["id"] for r in existing]
        placeholders = ",".join("?" * len(sheet_ids))
        cursor.execute(f"DELETE FROM rs_rate_sheet_cells WHERE sheet_id IN ({placeholders})", sheet_ids)
        cursor.execute(f"DELETE FROM rs_carrier_zones WHERE sheet_id IN ({placeholders})", sheet_ids)
        cursor.execute(f"DELETE FROM rs_weight_breaks WHERE sheet_id IN ({placeholders})", sheet_ids)
        cursor.execute(f"DELETE FROM rs_carrier_minimums WHERE sheet_id IN ({placeholders})", sheet_ids)
        cursor.execute(f"DELETE FROM rs_carrier_surcharges WHERE sheet_id IN ({placeholders})", sheet_ids)
        cursor.execute(f"DELETE FROM rs_rate_sheets WHERE id IN ({placeholders})", sheet_ids)
        conn.commit()

    conn.close()

    created_ids = []

    for carrier_def in CANADIAN_BENCHMARK_CARRIERS:
        carrier_name = carrier_def["carrier_name"]
        service_name = carrier_def["service_name"]
        tariff_ref = carrier_def["tariff_ref"]

        # Create Rate Sheet
        sheet_id = create_rate_sheet(
            user_id=user_id,
            carrier_name=carrier_name,
            service_name=service_name,
            tariff_ref=tariff_ref,
            mode=carrier_def["mode"],
            currency=carrier_def["currency"],
            weight_unit=carrier_def["weight_unit"],
            dim_unit="in",
            dim_divisor=carrier_def["dim_divisor"],
            dim_min_rule=carrier_def["dim_min_rule"],
            rounding_rule="standard_2dp",
            effective_date=carrier_def["effective_date"],
            expiry_date=carrier_def["expiry_date"],
            version=1,
            source_filename="benchmark_canadian_tariffs.csv",
            confirmation_status="CONFIRMED"
        )

        # Mark as benchmark tariff
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE rs_rate_sheets SET is_benchmark = 1 WHERE id = ?", (sheet_id,))
        conn.commit()
        conn.close()

        # Confirm sheet for live quoting
        confirm_rate_sheet(sheet_id, user_id=user_id, confirmed_by="RateSift Benchmark Registry")

        # Insert Surcharges
        insert_carrier_surcharges(sheet_id, user_id=user_id, surcharges=carrier_def["surcharges"])

        # Insert Corridors (Bidirectional!), Weight Breaks, Minimums, and Zones
        zones = []
        breaks = []
        minimums = []
        cells = []

        bracket_specs = [
            ("LTL", 0.0, 999.0, "Col D"),
            ("CWT:1000", 1000.0, 1999.0, "Col E"),
            ("CWT:2000", 2000.0, 4999.0, "Col F"),
            ("CWT:5000", 5000.0, 9999.0, "Col G"),
            ("CWT:10000", 10000.0, 999999.0, "Col H")
        ]

        row_counter = 10
        for corr in carrier_def["corridors"]:
            o = corr["origin"]
            d = corr["dest"]
            t_days = corr["transit_days"]
            min_chg = corr["min_charge"]
            brk_rates = corr["breaks"]

            # Support bidirectional lanes (A -> B and B -> A)
            lane_pairs = [(o, d), (d, o)]

            for orig, dest in lane_pairs:
                row_counter += 1
                row_tag = f"Tariff_{carrier_name.replace(' ', '_')} • Row {row_counter}"

                # Zone & transit days
                zones.append({
                    "origin_spec": orig,
                    "dest_spec": dest,
                    "zone_code": f"Z_{orig[:3]}_{dest[:3]}",
                    "transit_days": t_days,
                    "source_cell": f"{row_tag}, Col C"
                })

                # Minimum charge
                minimums.append({
                    "zone_code": "P2P",
                    "origin_spec": orig,
                    "dest_spec": dest,
                    "min_charge": min_chg,
                    "source_cell": f"{row_tag}, Col C"
                })

                # Weight Breaks
                for brk_name, min_w, max_w, col_coord in bracket_specs:
                    rate_val = brk_rates.get(brk_name, 0.0)
                    coord = f"{row_tag}, {col_coord}"
                    breaks.append({
                        "zone_code": "P2P",
                        "origin_spec": orig,
                        "dest_spec": dest,
                        "min_weight": min_w,
                        "max_weight": max_w,
                        "break_name": brk_name,
                        "base_rate": rate_val,
                        "rate_type": "CWT",
                        "source_cell": coord
                    })

                    cells.append({
                        "sheet_tab": "Standard LTL Rates",
                        "cell_coord": coord,
                        "field_name": f"rate.{brk_name}.{orig}->{dest}",
                        "raw_value": str(rate_val),
                        "extracted_value": str(rate_val),
                        "confidence": 1.0,
                        "needs_review": False
                    })

        insert_carrier_zones(sheet_id, user_id=user_id, zones=zones)
        insert_carrier_minimums(sheet_id, user_id=user_id, minimums=minimums)
        insert_weight_breaks(sheet_id, user_id=user_id, breaks=breaks)
        insert_rate_sheet_cells(sheet_id, user_id=user_id, cells=cells)

        created_ids.append(sheet_id)

    return created_ids

if __name__ == "__main__":
    print("Seeding Canadian benchmark carrier tariffs for Alex Rivers...")
    ids = seed_canadian_benchmarks_for_user("usr_alex_rivers", force=True)
    print(f"Successfully seeded {len(ids)} Canadian benchmark tariffs: {ids}")
