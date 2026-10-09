"""Unit tests for hardened detection (Phase 1B)."""
import pytest
from openpyxl import Workbook
from app.detect import analyze, load_rows, parse_break_value, validate_mapping


def make_sheet(rows, path):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


def test_break_parsing_formats():
    assert parse_break_value("-45") == (45.0, None)
    assert parse_break_value("+100") == (100.0, None)
    assert parse_break_value("100+") == (100.0, None)
    assert parse_break_value("100-499") == (100.0, None)
    assert parse_break_value("45 lb") == (45.0, "lb")
    assert parse_break_value("45#") == (45.0, "lb")
    assert parse_break_value("500 kgs") == (500.0, "kg")
    assert parse_break_value(100) == (100.0, None)


def test_clean_weight_sheet_with_unit_is_ready(tmp_path):
    rows = [
        ["ACME Freight Rates 2026 (Rates in lbs)"],
        [],
        ["Origin", "Destination", "Min", "-45", "+100", "+500", "+1000"],
        ["Toronto", "Montreal", 85, 0.55, 0.42, 0.35, 0.30],
        ["Toronto", "Calgary", 120, 0.80, 0.66, 0.55, 0.48],
    ]
    path = make_sheet(rows, tmp_path / "clean_weight.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["status"] == "ready"
    assert r["mode"] == "weight"
    assert r["weight_unit"] == "lb"
    assert r["unresolved"] == []


def test_weight_sheet_no_unit_goes_to_needs_mapping(tmp_path):
    # Rule 8: Weight unit is required in weight mode. Missing unit must not reach ready.
    rows = [
        ["ACME Freight Rates 2026"],
        [],
        ["Origin", "Destination", "Min", "-45", "+100", "+500", "+1000"],
        ["Toronto", "Montreal", 85, 0.55, 0.42, 0.35, 0.30],
        ["Toronto", "Calgary", 120, 0.80, 0.66, 0.55, 0.48],
    ]
    path = make_sheet(rows, tmp_path / "no_unit.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["status"] == "needs_mapping"
    assert r["mode"] == "weight"
    assert "weight_unit" in r["unresolved"]


def test_skid_sheet_column_layout(tmp_path):
    rows = [
        ["From", "To", "1 PL", "2 PL", "3 PL"],
        ["Hamilton", "Ottawa", 210, 380, 540],
        ["Hamilton", "Windsor", 180, 330, 470],
    ]
    path = make_sheet(rows, tmp_path / "skid_cols.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["mode"] == "skid"
    assert r["status"] == "needs_mapping"  # Skid mode requires confirmation per Rule 4


def test_skid_sheet_row_layout(tmp_path):
    rows = [
        ["From", "To", "Pallet Count", "Rate"],
        ["Toronto", "Montreal", 1, 150.0],
        ["Toronto", "Montreal", 2, 280.0],
        ["Toronto", "Montreal", 3, 400.0],
    ]
    path = make_sheet(rows, tmp_path / "skid_row.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["mode"] == "skid"
    skid_guess = next((g for g in r["guesses"] if g["field"] == "skid_rates"), None)
    assert skid_guess is not None
    # Columns for skid count (2) and rate (3)
    assert skid_guess["columns"] == [2, 3]


def test_sheet_with_both_modes_prompts_user(tmp_path):
    # Rule 3: Sheet with both modes asks the user which one to quote
    rows = [
        ["From", "To", "100 lbs", "500 lbs", "1 PL", "2 PL"],
        ["Toronto", "Montreal", 0.50, 0.40, 200, 350],
    ]
    path = make_sheet(rows, tmp_path / "both_modes.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["status"] == "needs_mapping"
    assert "mode" in r["unresolved"]


def test_sheet_with_neither_mode_prompts_user(tmp_path):
    rows = [
        ["Origin", "Destination", "Notes", "Status"],
        ["Toronto", "Montreal", "Dry goods", "Active"],
    ]
    path = make_sheet(rows, tmp_path / "neither_mode.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["status"] == "needs_mapping"
    assert "mode" in r["unresolved"]


def test_unrecognisable_headers_trigger_prompt(tmp_path):
    # Rule 5: Content alone never auto-maps a required field
    rows = [
        ["Col A", "Col B", "Col C", "Col D"],
        ["Toronto", "Montreal", 100, 200],
        ["Toronto", "Calgary", 150, 260],
    ]
    path = make_sheet(rows, tmp_path / "unrecognised.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["status"] == "needs_mapping"
    assert {"origin", "destination", "mode"} <= set(r["unresolved"])


def test_conflicting_origin_candidates_triggers_conflict(tmp_path):
    # Rule 6: Two columns strongly matching the same field trigger conflict
    rows = [
        ["Origin City", "Ship From", "Destination", "100 lbs", "500 lbs"],
        ["Toronto", "Toronto", "Montreal", 0.50, 0.40],
    ]
    path = make_sheet(rows, tmp_path / "conflict.xlsx")
    r = analyze(load_rows(path, ".xlsx"))
    assert r["status"] == "needs_mapping"
    assert "origin" in r["unresolved"]
    assert len(r["conflicts"]) > 0
    assert any(c["field"] == "origin" for c in r["conflicts"])


def test_valid_mapping_passes(tmp_path):
    rows = [
        ["Origin", "Destination", "-45", "+100", "+500"],
        ["Toronto", "Montreal", 0.55, 0.45, 0.35],
    ]
    assert validate_mapping(rows, 0, "weight", 0, 1, [2, 3, 4], "lb") == []


def test_invalid_mapping_reports_all_problems(tmp_path):
    rows = [
        ["Origin", "Destination", "+500", "+100"],
        ["Toronto", "Montreal", 0.55, 0.45],
    ]
    # Same column for origin and dest, missing unit, descending breaks
    errs = validate_mapping(rows, 0, "weight", 0, 0, [2, 3], None)
    joined = " ".join(errs)
    assert "same column" in joined
    assert "unit" in joined
    assert "ascending" in joined
