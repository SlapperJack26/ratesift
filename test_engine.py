import os
import uuid
from services.db_service import init_db, get_connection
from services.parser_service import parse_excel_rate_sheet
from services.rating_service import calculate_batch_quotes
from services.auth_service import authenticate_user, get_user_profile, register_and_create_session

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
    test_email = f"engine.user.{uuid.uuid4().hex[:6]}@acme-freight.ca"
    test_pwd = "EngineTestPassword2026!"
    reg_user, _ = register_and_create_session(
        name="Jordan Freight",
        email=test_email,
        company="Acme Freight Systems",
        origin_zip="M5V 2T6",
        password=test_pwd
    )
    user = authenticate_user(test_email, test_pwd)
    assert user is not None
    profile = get_user_profile(reg_user["id"])
    print(f"   Authenticated: {user['name']} ({user['company']}), Tier: {user['tier']}, Origin ZIP: {profile['origin_zip']}")

    print("\nALL BACKEND CORE VERIFICATIONS PASSED!")

if __name__ == "__main__":
    test()
