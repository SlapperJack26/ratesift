import os
from services.db_service import init_db, get_connection
from services.parser_service import parse_excel_rate_sheet
from services.rating_service import calculate_batch_quotes
from services.auth_service import authenticate_user, get_user_profile

def test():
    print("1. Testing Database Initialization...")
    init_db()
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT count(*) as count FROM users")
    user_count = c.fetchone()["count"]
    print(f"   Database active. Seeded users count: {user_count}")
    conn.close()

    print("\n2. Testing Excel Parser & Coordinate Mapping...")
    sample_file = "sample_sheets/ecommerce_parcels.xlsx"
    with open(sample_file, "rb") as f:
        file_bytes = f.read()
    parse_result = parse_excel_rate_sheet(file_bytes, "ecommerce_parcels.xlsx")
    print(f"   Sheet: {parse_result['sheet_name']}, Header Row: {parse_result['header_row']}, Total Rows: {parse_result['total_parsed_rows']}")
    assert parse_result["total_parsed_rows"] == 7
    print(f"   Row 1 Coordinate: {parse_result['rows'][0]['coordinate']}")

    print("\n3. Testing Rating Engine with +10% Markup...")
    quotes = calculate_batch_quotes(parse_result["rows"], markup_pct=10.0)
    print(f"   Generated {len(quotes)} quote line items.")
    for q in quotes[:3]:
        print(f"   - Quote {q['quote_id']}: {q['origin_zip']} -> {q['dest_zip']}, {q['weight_lbs']} lbs | {q['carrier']} ({q['service']}) | Base: ${q['base_rate']} -> Final (+10%): ${q['final_rate']} | [{q['coordinate']}]")

    print("\n4. Testing User Profile & Auth...")
    user = authenticate_user("alex.rivers@techcorp.io", "demo123")
    profile = get_user_profile("usr_alex_rivers")
    print(f"   Authenticated: {user['name']} ({user['company']}), Tier: {user['tier']}, Origin ZIP: {profile['origin_zip']}")

    print("\nALL BACKEND CORE VERIFICATIONS PASSED!")

if __name__ == "__main__":
    test()
