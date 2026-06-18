import hashlib
import html
import json
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlsplit

from .sites import SITE_REGISTRY, site_for_url


def clean_text(raw_html: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def page_title(raw_html: str, fallback: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw_html)
    title = clean_text(match.group(1)) if match else fallback
    return re.sub(r"[_\-|—].*$", "", title).strip()[:300] or fallback


def evidence_item(source_type: str, source_site: str, url: str, target_name: str, field: str, value, evidence: str, confidence: float) -> dict:
    evidence = evidence.strip()[:800]
    fingerprint = f"{source_site}|{url}|{target_name}|{field}|{json.dumps(value, ensure_ascii=False, sort_keys=True)}|{evidence}"
    return {
        "item_id": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:32],
        "source_type": source_type,
        "source_site": source_site,
        "source_domain": urlsplit(url).hostname or "",
        "source_url": url,
        "target_name": target_name[:300],
        "field_name": field,
        "field_value": value,
        "evidence_text": evidence,
        "content_hash": hashlib.sha256(clean_text(evidence).encode("utf-8")).hexdigest(),
        "confidence": confidence,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


class BaseAdapter(ABC):
    source_type = "official"
    source_site = "official"

    @abstractmethod
    def extract(self, url: str, raw_html: str) -> list[dict]:
        raise NotImplementedError

    def _context(self, text: str, match: re.Match, width: int = 90) -> str:
        return text[max(0, match.start() - width): min(len(text), match.end() + width)]

    def _item(self, url: str, target: str, field: str, value, evidence: str, confidence: float) -> dict:
        return evidence_item(self.source_type, self.source_site, url, target, field, value, evidence, confidence)


class SearchAdapter(ABC):
    @abstractmethod
    def discover(self, raw_html: str) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def _safe_candidates(candidates: list[str]) -> list[str]:
        result = []
        for value in candidates:
            value = html.unescape(unquote(value)).strip()
            if value.startswith(("http://", "https://")) and value not in result:
                result.append(value)
        return result[:12]


class BaiduSearchAdapter(SearchAdapter):
    def discover(self, raw_html: str) -> list[str]:
        candidates = re.findall(r'(?i)(?:data-landurl|mu)=["\'](https?://[^"\']+)', raw_html)
        candidates.extend(re.findall(r'(?i)href=["\'](https?://(?:www\.)?baidu\.com/link\?[^"\']+)', raw_html))
        return self._safe_candidates(candidates)


class BingSearchAdapter(SearchAdapter):
    def discover(self, raw_html: str) -> list[str]:
        blocks = re.findall(r'(?is)<li[^>]+class=["\'][^"\']*b_algo[^"\']*["\'][^>]*>(.*?)</li>', raw_html)
        candidates = []
        for block in blocks:
            match = re.search(r'(?is)<h2[^>]*>.*?<a[^>]+href=["\'](https?://[^"\']+)', block)
            if match:
                candidates.append(match.group(1))
        if not candidates:
            candidates = re.findall(r'(?i)href=["\'](https?://[^"\']+)', raw_html)
        decoded = []
        for candidate in candidates:
            parsed = urlsplit(html.unescape(candidate))
            query = parse_qs(parsed.query)
            decoded.append((query.get("url") or query.get("u") or [candidate])[0])
        return self._safe_candidates(decoded)


class OfficialAdapter(BaseAdapter):
    source_type = "official"
    source_site = "official"
    patterns = {
        "business_hours": re.compile(r"(?:营业时间|营业时段|营业)[：:\s]*([^。；]{3,50})"),
        "configuration": re.compile(r"(?:机器配置|电脑配置|主机配置|显卡|处理器)[：:\s]*([^。；]{3,140})"),
        "machine_count": re.compile(r"(?:机器数量|电脑数量|机位数量|机位)[：:\s]*(\d{1,4})\s*(?:台|个|席)?"),
        "area_sqm": re.compile(r"(?:营业面积|门店面积|场地面积|面积)[：:\s]*([0-9,.]+)\s*(?:㎡|平方米|平米)"),
        "hourly_price": re.compile(r"(?:网费|小时价|每小时|小时收费)[：:\s]*(\d+(?:\.\d+)?)\s*元"),
        "package_price": re.compile(r"(?:套餐|包时|夜包|通宵)[^。；]{0,35}?(\d+(?:\.\d+)?)\s*元"),
        "recharge_info": re.compile(r"((?:充值|充)[^。；]{3,100}(?:赠|送)[^。；]{0,60})"),
        "opening_info": re.compile(r"((?:开业|试营业|盛大开业)[^。；]{0,100})"),
    }

    def extract(self, url: str, raw_html: str) -> list[dict]:
        text = clean_text(raw_html)
        target = page_title(raw_html, urlsplit(url).hostname or "竞品官网")
        items = []
        for field, pattern in self.patterns.items():
            match = pattern.search(text)
            if not match:
                continue
            value = match.group(1).strip().replace(",", "")
            if field in {"hourly_price", "package_price", "area_sqm"}:
                value = float(value)
            elif field == "machine_count":
                value = int(value)
            items.append(self._item(url, target, field, value, self._context(text, match), 0.78))
        return items


class PropertyAdapter(BaseAdapter):
    source_type = "property"
    source_site = "property"
    confidence = 0.72
    area_patterns = (re.compile(r"(?:建筑面积|商铺面积|面积)[：:\s]*([0-9,.]+)\s*(?:㎡|平方米|平米|平)"),)
    rent_patterns = (
        re.compile(r"(?:月租|租金|价格)[：:\s]*([0-9,.]+)\s*(万元/月|万/月|元/月|元/天|元/(?:㎡|平米)[·・/]?天)"),
    )
    floor_patterns = (re.compile(r"(?:所在楼层|楼层)[：:\s]*(.{1,30}?)(?=\s*(?:详细地址|商铺地址|地址|位置|发布时间|更新时间|房源更新时间)|[。；|]|$)"),)
    address_patterns = (re.compile(r"(?:详细地址|商铺地址|地址|位置)[：:\s]*(.{4,160}?)(?=\s*(?:发布时间|发布于|更新时间|房源更新时间)|[。；|]|$)"),)
    date_patterns = (re.compile(r"(?:发布时间|发布于|更新时间)[：:\s]*([0-9]{4}[-年/.][0-9]{1,2}[-月/.][0-9]{1,2}日?)"),)

    @staticmethod
    def _first(patterns: tuple[re.Pattern, ...], text: str):
        return next((match for pattern in patterns if (match := pattern.search(text))), None)

    @staticmethod
    def _rent_values(amount: float, unit: str, area: float | None) -> tuple[float | None, dict]:
        normalized = unit.replace("・", "·").replace("/平米", "/㎡")
        monthly = None
        if normalized in {"万元/月", "万/月"}:
            monthly = amount * 10000
        elif normalized == "元/月":
            monthly = amount
        elif normalized == "元/天":
            monthly = amount * 30
        elif "元/㎡" in normalized and area:
            monthly = amount * area * 30
        return monthly, {"amount": amount, "unit": unit, "calculation": "公开单价×面积×30天" if "元/㎡" in normalized and area else "公开租金单位换算"}

    def extract(self, url: str, raw_html: str) -> list[dict]:
        text = clean_text(raw_html)
        definition = SITE_REGISTRY.get(self.source_site)
        target = page_title(raw_html, f"{definition.label if definition else '公开商铺'}公开房源")
        items = []
        area_match = self._first(self.area_patterns, text)
        area = float(area_match.group(1).replace(",", "")) if area_match else None
        if area_match:
            items.append(self._item(url, target, "area_sqm", area, self._context(text, area_match), self.confidence))
        rent_match = self._first(self.rent_patterns, text)
        if rent_match:
            amount = float(rent_match.group(1).replace(",", ""))
            unit = rent_match.group(2)
            monthly, unit_value = self._rent_values(amount, unit, area)
            items.append(self._item(url, target, "rent_unit_price", unit_value, self._context(text, rent_match), self.confidence))
            if monthly is not None:
                items.append(self._item(url, target, "monthly_rent", round(monthly, 2), self._context(text, rent_match), self.confidence - 0.04))
        for field, patterns in (("floor", self.floor_patterns), ("address", self.address_patterns), ("published_at", self.date_patterns)):
            match = self._first(patterns, text)
            if match:
                items.append(self._item(url, target, field, match.group(1).strip(), self._context(text, match), self.confidence))
        return items


class FiftyEightPropertyAdapter(PropertyAdapter):
    source_site = "58"
    confidence = 0.73
    rent_patterns = (
        re.compile(r"(?:租金|价格)[：:\s]*([0-9,.]+)\s*(元/㎡/天|元/平米·天|元/月|万元/月|万/月)"),
        *PropertyAdapter.rent_patterns,
    )
    floor_patterns = PropertyAdapter.floor_patterns


class AnjukePropertyAdapter(PropertyAdapter):
    source_site = "anjuke"
    confidence = 0.74
    area_patterns = (
        re.compile(r"(?:面积|建筑面积)[：:\s]*([0-9,.]+)\s*(?:m²|㎡|平米|平方米)"),
        *PropertyAdapter.area_patterns,
    )
    rent_patterns = (
        re.compile(r"(?:租金|价格)[：:\s]*([0-9,.]+)\s*(元/平米/天|元/㎡/天|元/月|万元/月|万/月)"),
        *PropertyAdapter.rent_patterns,
    )


class FangPropertyAdapter(PropertyAdapter):
    source_site = "fang"
    confidence = 0.75
    rent_patterns = (
        re.compile(r"(?:租金|报价)[：:\s]*([0-9,.]+)\s*(元/平米·天|元/㎡/天|元/月|万元/月|万/月)"),
        *PropertyAdapter.rent_patterns,
    )
    date_patterns = (
        re.compile(r"(?:房源更新时间|更新时间|发布时间)[：:\s]*([0-9]{4}[-年/.][0-9]{1,2}[-月/.][0-9]{1,2}日?)"),
        *PropertyAdapter.date_patterns,
    )


class GovernmentAdapter(BaseAdapter):
    source_type = "government"
    source_site = "gov"
    policy_pattern = re.compile(r"([^。；]{0,120}(?:互联网上网服务|网吧|电竞酒店|行政处罚|经营许可|消防|未成年人|文化市场|学校周边)[^。；]{0,220}[。；]?)")
    number_pattern = re.compile(r"((?:[\u4e00-\u9fa5]{1,12})?(?:规|办|发|函|令|公告)〔?\d{4}〕?\d+号)")
    date_pattern = re.compile(r"(?:发布时间|发布日期|成文日期)[：:\s]*([0-9]{4}[-年]\d{1,2}[-月]\d{1,2}日?)")
    authority_pattern = re.compile(r"(?:发布机构|发文机关|来源)[：:\s]*(.{2,80}?)(?=\s*(?:发布日期|发布时间|成文日期|[\u4e00-\u9fa5]{1,12}(?:规|办|发|函|令|公告)〔?\d{4})|[。；|]|$)")

    def extract(self, url: str, raw_html: str) -> list[dict]:
        text = clean_text(raw_html)
        target = page_title(raw_html, "政府公开文件")
        items = []
        for match in list(self.policy_pattern.finditer(text))[:8]:
            snippet = match.group(1).strip()
            items.append(self._item(url, target, "policy_note", snippet, snippet, 0.86))
        for field, pattern in (("document_number", self.number_pattern), ("published_at", self.date_pattern), ("issuing_authority", self.authority_pattern)):
            match = pattern.search(text)
            if match:
                items.append(self._item(url, target, field, match.group(1).strip(), self._context(text, match), 0.88))
        return items


SEARCH_ADAPTERS = {"baidu": BaiduSearchAdapter(), "bing": BingSearchAdapter()}
EVIDENCE_ADAPTERS = {
    "official": OfficialAdapter(),
    "58": FiftyEightPropertyAdapter(),
    "anjuke": AnjukePropertyAdapter(),
    "fang": FangPropertyAdapter(),
    "gov": GovernmentAdapter(),
}


# Backward-compatible aliases used by older tests and jobs.
ADAPTERS = {"official": EVIDENCE_ADAPTERS["official"], "property": EVIDENCE_ADAPTERS["58"], "government": EVIDENCE_ADAPTERS["gov"]}


def source_for_url(url: str, requested: list[str]) -> str | None:
    site = site_for_url(url, requested)
    return SITE_REGISTRY[site].source_type if site else None
