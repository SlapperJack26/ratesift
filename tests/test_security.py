"""Tests for formula and file security (Phase 1A and Phase 3/6)"""
from app.output_safety import sanitize_cell_value


def test_sanitize_formula_injection():
    assert sanitize_cell_value("=HYPERLINK()") == "'=HYPERLINK()"
    assert sanitize_cell_value("+SUM(1,2)") == "'+SUM(1,2)"
    assert sanitize_cell_value("-100") == "'-100"
    assert sanitize_cell_value("@test") == "'@test"
    assert sanitize_cell_value(42) == 42
    assert sanitize_cell_value("Normal Text") == "Normal Text"
