"""
Formula-safe writing helpers:
Sanitizes any cell string starting with =, +, -, @ to prevent formula injection.
Numbers (e.g. negative floats/ints) remain native numbers.
"""
from typing import Any
import openpyxl


def sanitize_cell_value(val: Any) -> Any:
    """Neutralize potential spreadsheet formula triggers for string values."""
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{val}"
    return val


def sanitize_workbook(wb: openpyxl.Workbook) -> None:
    """Sanitizes all cells across all worksheets in the workbook in place."""
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=False):
            for cell in row:
                if isinstance(cell.value, str) and cell.value and cell.value[0] in ("=", "+", "-", "@", "\t", "\r"):
                    cell.value = f"'{cell.value}"
