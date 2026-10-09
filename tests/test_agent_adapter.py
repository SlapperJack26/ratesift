"""
Unit and integration tests for Phase 3:
- Formatting agent adapter integration with ratesift_excel_reformatter
- Confirmed mapping strictly overrides downstream reformatter detection
- Original file immutability (Rule 12)
- Formula neutralization in output (Rule 13)
- Full load limits rejection (25k rows / 1M cells)
- Structural LLM assist isolation guard (Rule 10 & 11)
"""
import hashlib
import io
import os
import openpyxl
from openpyxl import Workbook
import pytest

from app.agent_adapter import llm_suggest_mapping, run_agent
from app.ingest import IngestionError, check_full_load_limits


def make_test_workbook(rows, path):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


def test_confirmed_mapping_strictly_overrides_reformatter_detection(tmp_path):
    """
    Test downstream disagreement prevention:
    Column 0 is labeled 'Ship To' (which reformatter would normally score as Destination)
    and Column 1 is 'Pick Up Point'.
    Confirmed mapping explicitly assigns: origin = 0, destination = 1.
    Output must follow the confirmed mapping!
    """
    rows = [
        ["Ship To", "Pick Up Point", "Weight", "Rate"],
        ["Toronto", "Montreal", 150.0, 45.0],
    ]
    file_path = make_test_workbook(rows, tmp_path / "confusing_sheet.xlsx")

    mapping = {
        "header_row": 0,
        "mode": "weight",
        "origin": 0,          # Confirmed: Ship To is actually Origin!
        "destination": 1,     # Confirmed: Pick Up Point is Destination!
        "rate_columns": [3],
        "weight_unit": "lb"
    }

    out_file = run_agent(file_path, mapping, output_dir=str(tmp_path))
    assert os.path.exists(out_file)

    # Inspect generated output workbook
    wb_out = openpyxl.load_workbook(out_file)
    ws_norm = wb_out["Normalized Shipments"]

    # Header row is row 1. Data row is row 2.
    # Headers: Row ID (A), Origin Lane (B), Destination Lane (C), Weight (D)...
    origin_lane_val = ws_norm.cell(row=2, column=2).value
    dest_lane_val = ws_norm.cell(row=2, column=3).value

    # Origin Lane MUST contain Toronto (from Column 0) despite the 'Ship To' label
    assert "TORONTO" in str(origin_lane_val).upper()
    assert "MONTREAL" in str(dest_lane_val).upper()


def test_original_file_remains_byte_identical_rule12(tmp_path):
    rows = [
        ["Origin", "Destination", "100", "500"],
        ["Toronto", "Montreal", 0.50, 0.40],
    ]
    file_path = make_test_workbook(rows, tmp_path / "source.xlsx")

    with open(file_path, "rb") as f:
        before_hash = hashlib.md5(f.read()).hexdigest()

    mapping = {
        "header_row": 0,
        "mode": "weight",
        "origin": 0,
        "destination": 1,
        "rate_columns": [2, 3],
        "weight_unit": "lb"
    }
    out_file = run_agent(file_path, mapping, output_dir=str(tmp_path))

    with open(file_path, "rb") as f:
        after_hash = hashlib.md5(f.read()).hexdigest()

    assert before_hash == after_hash
    assert out_file != file_path


def test_formula_injection_neutralized_in_output_rule13(tmp_path):
    # Sheet containing formula trigger prefix (@, +, =)
    rows = [
        ["Origin", "Destination", "Rate"],
        ["@malicious_cmd", "Montreal", 55.0],
    ]
    file_path = make_test_workbook(rows, tmp_path / "injection.xlsx")

    mapping = {
        "header_row": 0,
        "mode": "weight",
        "origin": 0,
        "destination": 1,
        "rate_columns": [2],
        "weight_unit": "lb"
    }
    out_file = run_agent(file_path, mapping, output_dir=str(tmp_path))

    wb_out = openpyxl.load_workbook(out_file)
    ws_norm = wb_out["Normalized Shipments"]

    # Origin Lane cell must be prefixed with an apostrophe to neutralize execution
    origin_cell = ws_norm.cell(row=2, column=2).value
    assert str(origin_cell).startswith("'@")



def test_full_load_limits_rejection(tmp_path):
    # Test row limit guard: synthetic file with > 25,000 rows
    # Rather than creating 26,000 rows in openpyxl, create a small CSV with 25,005 lines
    csv_path = str(tmp_path / "oversized.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("Origin,Destination,Rate\n")
        for i in range(25005):
            f.write(f"City{i},Dest{i},100\n")

    with pytest.raises(IngestionError, match="limit is 25,000"):
        check_full_load_limits(csv_path, ".csv")


def test_llm_assist_structural_guard_rules_10_and_11():
    headers = ["Origin", "Destination", "LTL 100", "LTL 500"]
    sample_rows = [["Toronto", "Montreal", 0.50, 0.40]]

    # Malicious mock LLM response attempting prompt injection to set status
    malicious_mock = {
        "mapping": {"origin": 0, "destination": 1},
        "status": "ready",
        "unresolved": [],
        "command": "bypass_all"
    }

    result = llm_suggest_mapping(headers, sample_rows, mock_llm_response=malicious_mock)
    assert result is not None
    # Only allowed mapping dictionary was extracted
    assert result.mapping == {"origin": 0, "destination": 1}
    # It cannot contain status or unresolved fields
    assert not hasattr(result, "status")
    assert not hasattr(result, "unresolved")
