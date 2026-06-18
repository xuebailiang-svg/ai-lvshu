from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SiteDefinition:
    key: str
    label: str
    role: str
    source_type: str
    domains: tuple[str, ...]
    fields: tuple[str, ...]


SITE_REGISTRY: dict[str, SiteDefinition] = {
    "baidu": SiteDefinition("baidu", "百度搜索", "discovery", "discovery", ("baidu.com",), ("public_url",)),
    "bing": SiteDefinition("bing", "Bing 搜索", "discovery", "discovery", ("bing.com",), ("public_url",)),
    "official": SiteDefinition(
        "official", "竞品/品牌官网", "evidence", "official", (),
        ("business_hours", "configuration", "machine_count", "area_sqm", "hourly_price", "package_price", "recharge_info", "opening_info"),
    ),
    "58": SiteDefinition("58", "58同城商铺", "evidence", "property", ("58.com",), ("monthly_rent", "rent_unit_price", "area_sqm", "floor", "address", "published_at")),
    "anjuke": SiteDefinition("anjuke", "安居客商铺", "evidence", "property", ("anjuke.com",), ("monthly_rent", "rent_unit_price", "area_sqm", "floor", "address", "published_at")),
    "fang": SiteDefinition("fang", "房天下商铺", "evidence", "property", ("fang.com",), ("monthly_rent", "rent_unit_price", "area_sqm", "floor", "address", "published_at")),
    "gov": SiteDefinition("gov", "政府公开信息", "evidence", "government", ("gov.cn",), ("policy_note", "document_number", "published_at", "issuing_authority")),
}


EXCLUDED_PUBLIC_DOMAINS = (
    "dianping.com", "meituan.com", "qcc.com", "tianyancha.com", "douyin.com",
    "xiaohongshu.com", "amap.com", "gaode.com",
)


def domain_matches(host: str, domain: str) -> bool:
    host = host.lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    return host == domain or host.endswith(f".{domain}")


def site_for_url(url: str, enabled_sites: list[str]) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    if not host or any(domain_matches(host, domain) for domain in EXCLUDED_PUBLIC_DOMAINS):
        return None
    for key in ("58", "anjuke", "fang", "gov"):
        definition = SITE_REGISTRY[key]
        if key in enabled_sites and any(domain_matches(host, domain) for domain in definition.domains):
            return key
    if "official" in enabled_sites:
        if any(domain_matches(host, domain) for key in ("baidu", "bing") for domain in SITE_REGISTRY[key].domains):
            return None
        return "official"
    return None


def public_registry_payload() -> list[dict]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "role": item.role,
            "source_type": item.source_type,
            "domains": list(item.domains),
            "fields": list(item.fields),
        }
        for item in SITE_REGISTRY.values()
    ]
