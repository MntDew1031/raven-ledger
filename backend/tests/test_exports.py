from app.api.households import _safe_csv_cell


def test_csv_cells_neutralize_spreadsheet_formulas():
    for prefix in ("=", "+", "-", "@", "\t", "\r"):
        value = f"{prefix}dangerous"
        assert _safe_csv_cell(value) == f"'{value}"


def test_csv_cells_leave_ordinary_text_unchanged():
    assert _safe_csv_cell("Normal merchant") == "Normal merchant"
    assert _safe_csv_cell("") == ""
