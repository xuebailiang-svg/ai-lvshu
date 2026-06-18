from pathlib import Path

from app.adapters import (
    AnjukePropertyAdapter,
    BaiduSearchAdapter,
    BingSearchAdapter,
    FangPropertyAdapter,
    FiftyEightPropertyAdapter,
    GovernmentAdapter,
    OfficialAdapter,
    PropertyAdapter,
)
from app.sites import site_for_url


FIXTURES = Path(__file__).parent / "fixtures"


def fields(items):
    return {item["field_name"]: item for item in items}


def test_official_adapter_extracts_supported_public_fields():
    items = fields(OfficialAdapter().extract("https://brand.example/store/1", (FIXTURES / "official.html").read_text(encoding="utf-8")))
    assert items["hourly_price"]["field_value"] == 12.0
    assert items["package_price"]["field_value"] == 49.0
    assert "RTX 4070" in items["configuration"]["field_value"]
    assert all(item["evidence_text"] and item["content_hash"] for item in items.values())


def test_property_adapter_extracts_numbers_without_guessing():
    items = fields(PropertyAdapter().extract("https://example.58.com/shangpu/1", (FIXTURES / "property.html").read_text(encoding="utf-8")))
    assert items["monthly_rent"]["field_value"] == 18000.0
    assert items["area_sqm"]["field_value"] == 320.0
    assert "fire_safety" not in items
    assert "power_capacity" not in items


def test_government_adapter_keeps_original_policy_evidence():
    items = GovernmentAdapter().extract("https://example.gov.cn/policy/1", (FIXTURES / "government.html").read_text(encoding="utf-8"))
    assert items
    assert any(item["field_name"] == "policy_note" for item in items)
    assert not any(item["field_name"] == "fire_safety" for item in items)
    extracted = fields(items)
    assert extracted["document_number"]["field_value"] == "测试文发〔2026〕12号"
    assert extracted["issuing_authority"]["field_value"] == "测试市文化和旅游局"


def test_same_url_and_content_produce_stable_ids_for_deduplication():
    raw = (FIXTURES / "official.html").read_text(encoding="utf-8")
    first = OfficialAdapter().extract("https://brand.example/store/1", raw)
    second = OfficialAdapter().extract("https://brand.example/store/1", raw)
    assert [item["item_id"] for item in first] == [item["item_id"] for item in second]
    assert len({item["item_id"] for item in first}) == len(first)


def test_58_adapter_converts_daily_square_meter_rent():
    items = fields(FiftyEightPropertyAdapter().extract("https://test.58.com/shangpu/123", (FIXTURES / "58.html").read_text(encoding="utf-8")))
    assert items["monthly_rent"]["field_value"] == 24000.0
    assert items["area_sqm"]["field_value"] == 320.0
    assert items["rent_unit_price"]["field_value"]["unit"] == "元/㎡/天"
    assert items["monthly_rent"]["source_site"] == "58"


def test_anjuke_adapter_has_independent_rules():
    items = fields(AnjukePropertyAdapter().extract("https://test.anjuke.com/shop/456", (FIXTURES / "anjuke.html").read_text(encoding="utf-8")))
    assert items["monthly_rent"]["field_value"] == 21600.0
    assert items["floor"]["field_value"] == "3层"
    assert items["monthly_rent"]["source_site"] == "anjuke"


def test_fang_adapter_converts_ten_thousand_yuan_monthly_rent():
    items = fields(FangPropertyAdapter().extract("https://shop.fang.com/zu/789", (FIXTURES / "fang.html").read_text(encoding="utf-8")))
    assert items["monthly_rent"]["field_value"] == 30000.0
    assert items["published_at"]["field_value"] == "2026年06月04日"
    assert items["monthly_rent"]["source_site"] == "fang"


def test_search_adapters_only_discover_urls():
    baidu = BaiduSearchAdapter().discover((FIXTURES / "baidu_search.html").read_text(encoding="utf-8"))
    bing = BingSearchAdapter().discover((FIXTURES / "bing_search.html").read_text(encoding="utf-8"))
    assert "https://brand.example/stores/test" in baidu
    assert "https://test.58.com/shangpu/123" in baidu
    assert "https://example.gov.cn/policy/123" in bing
    assert "https://test.anjuke.com/shop/456" in bing


def test_site_registry_blocks_out_of_scope_platforms():
    enabled = ["official", "58", "anjuke", "fang", "gov"]
    assert site_for_url("https://test.58.com/shangpu/1", enabled) == "58"
    assert site_for_url("https://city.example.gov.cn/policy/1", enabled) == "gov"
    assert site_for_url("https://brand.example/store/1", enabled) == "official"
    assert site_for_url("https://www.dianping.com/shop/1", enabled) is None
    assert site_for_url("https://www.meituan.com/shop/1", enabled) is None
