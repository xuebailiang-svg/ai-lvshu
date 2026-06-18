import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "backend" / "app" / "services" / "crawl_merge.py"
spec = importlib.util.spec_from_file_location("crawl_merge_testable", MODULE_PATH)
merge = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(merge)


def test_existing_manual_property_data_wins_over_crawl_value():
    result = merge.merge_property_conditions(
        {"monthly_rent": 18000, "area_sqm": None, "frontage_visibility": "good"},
        {"monthly_rent": 22000, "area_sqm": 320, "frontage_visibility": "unknown"},
    )
    assert result["monthly_rent"] == 18000
    assert result["area_sqm"] == 320
    assert result["frontage_visibility"] == "good"


def test_existing_manual_competitor_fields_win_and_missing_fields_fill():
    rows, row = merge.merge_competitor_rows(
        [{"name": "星云电竞", "hourly_price": 8, "configuration": ""}],
        "星云电竞",
        {"hourly_price": 12, "configuration": "RTX 4070"},
        {"source_site": "official"},
    )
    assert len(rows) == 1
    assert row["hourly_price"] == 8
    assert row["configuration"] == "RTX 4070"
