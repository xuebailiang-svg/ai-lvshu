"""
六维评分引擎
- 交通与人流
- 竞品分析
- 目标客群
- 租金与成本
- 配套设施
- 政策环境

每个维度从高德/美团 API 获取数据，结合历史权重进行评分
支持 SSE 流式日志输出（工作流可视化）
"""
import asyncio
import json
import logging
import math
from typing import Optional, AsyncGenerator
from sqlalchemy.orm import Session

from app.models.store import CompetitorProfile, DataQualityIssue, EvaluationRecord, ScoringModelVersion, ScoringRule
from app.services.amap import (
    geocode_address, search_poi_around, search_poi_around_pages, get_competitor_count, get_amap_key
)

logger = logging.getLogger(__name__)

# 默认评分半径（米）
DEFAULT_RADIUS = 1500


def get_active_model_version(db: Session, tenant_id: int) -> Optional[ScoringModelVersion]:
    return db.query(ScoringModelVersion).filter(
        ScoringModelVersion.tenant_id == tenant_id,
        ScoringModelVersion.is_active == True
    ).order_by(ScoringModelVersion.created_at.desc()).first()


def get_effective_weights(db: Session, tenant_id: int) -> dict:
    """从数据库获取当前生效的评分权重"""
    rules = db.query(ScoringRule).filter(
        ScoringRule.tenant_id == tenant_id,
        ScoringRule.is_active == True
    ).all()

    weights = {}
    for rule in rules:
        key = f"{rule.dimension}.{rule.sub_factor}" if rule.sub_factor else rule.dimension
        weights[key] = rule.effective_weight

    # 默认权重（当数据库无配置时）
    defaults = {
        "traffic.foot_traffic": 0.25,
        "traffic.transit_accessibility": 0.10,
        "competition.competitor_count": 0.20,
        "competition.competitor_distance": 0.05,
        "population.young_density": 0.20,
        "population.university_nearby": 0.05,
        "rent.rent_ratio": 0.10,
        "facility.commercial_density": 0.03,
        "policy.policy_risk": 0.02,
    }
    for k, v in defaults.items():
        if k not in weights:
            weights[k] = v

    return weights


def build_dimension_weight_map(weights: dict) -> dict:
    """把所有小类权重按大类汇总，支持用户新增小类。"""
    dimensions = ["traffic", "competition", "population", "rent", "facility", "policy"]
    dimension_weight_map = {dim: 0.0 for dim in dimensions}
    for key, value in weights.items():
        if value is None:
            continue
        dimension = str(key).split(".", 1)[0]
        if dimension not in dimension_weight_map:
            continue
        try:
            dimension_weight_map[dimension] += float(value)
        except (TypeError, ValueError):
            continue

    defaults = {
        "traffic": 0.35,
        "competition": 0.25,
        "population": 0.25,
        "rent": 0.10,
        "facility": 0.03,
        "policy": 0.02,
    }
    for dim, default in defaults.items():
        if dimension_weight_map.get(dim, 0) <= 0:
            dimension_weight_map[dim] = default
    return dimension_weight_map


FACTOR_LABELS = {
    "foot_traffic": "人流基础",
    "transit_accessibility": "公共交通可达性",
    "metro_distance": "地铁距离",
    "bus_distance": "公交距离",
    "negative_overpass": "高架桥阻隔",
    "negative_interchange": "立交桥阻隔",
    "negative_underpass": "地下隧道阻隔",
    "negative_railway": "火车道阻隔",
    "negative_greenbelt": "大型绿化带阻隔",
    "competitor_count": "竞品数量",
    "competitor_distance": "竞品距离",
    "competitor_configuration": "竞品配置",
    "competitor_price": "竞品价格",
    "competitor_occupancy": "竞品上座率",
    "competitor_open_years": "竞品经营年限",
    "competitor_area": "竞品面积",
    "competitor_monthly_sales": "竞品月售/月营收",
    "competitor_annual_sales": "竞品年售/年营收",
    "competitor_recharge": "竞品充值活动",
    "same_category_capacity": "同品类容量",
    "young_density": "18-35岁客群密度",
    "university_nearby": "大学/高职客群",
    "resident_population": "常住人口",
    "floating_population": "流动人口",
    "age_18_24": "18-24岁占比",
    "age_25_34": "25-34岁占比",
    "secondary_vocational_nearby": "中职/技校客群",
    "rent_ratio": "租金营收匹配",
    "area_sqm": "经营面积",
    "floor": "楼层",
    "frontage_visibility": "门头可见性",
    "parking_convenience": "停车便利性",
    "fire_safety": "消防条件",
    "property_restriction": "物业限制",
    "power_capacity": "电力容量",
    "hvac_exhaust": "空调/排烟",
    "commercial_density": "商业配套密度",
    "night_market": "夜市摊",
    "food_business_hours": "餐饮营业时间",
    "food_category": "餐饮品类",
    "food_open_years": "餐饮开业年限",
    "ktv": "KTV",
    "bar": "酒吧",
    "billiards": "台球厅",
    "escape_room": "密室/剧本杀",
    "cinema": "电影院",
    "convenience_24h": "24小时便利店",
    "relocation_housing": "回迁房",
    "apartment": "公寓",
    "policy_risk": "政策合规风险",
    "policy_redline_200m": "200m政策红线",
}


FACTOR_DESCRIPTIONS = {
    "foot_traffic": "衡量候选点周边基础人流和商业活跃度。",
    "transit_accessibility": "衡量公交、地铁等公共交通到达便利程度。",
    "metro_distance": "候选点到最近地铁/轻轨站的距离。",
    "bus_distance": "候选点到公交站的距离和线路覆盖。",
    "negative_overpass": "高架桥可能割裂人流、遮挡门头或降低步行体验，是减分因素。",
    "negative_interchange": "立交桥可能增加绕行和过街难度，是减分因素。",
    "negative_underpass": "地下隧道可能影响可见性、动线和安全感，是减分因素。",
    "negative_railway": "火车道可能割裂生活圈和商业动线，是减分因素。",
    "negative_greenbelt": "大型绿化带可能阻断步行路径，是减分因素。",
    "young_density": "18-35岁主力电竞消费人群密度，是潜在需求核心项。",
    "university_nearby": "周边大学、高职、中职等年轻客群，但需过滤小学、培训机构等误匹配。",
    "competitor_count": "周边有效电竞馆、网咖等竞品数量。",
    "competitor_distance": "竞品与候选点的距离，过近会直接分流。",
    "same_category_capacity": "根据客群、频次、客单价和健康月营收估算商圈剩余容量。",
    "rent_ratio": "租金与预期营收的匹配程度。",
    "commercial_density": "周边餐饮、便利店、娱乐、停车等配套密度。",
    "policy_risk": "证照、消防、物业、经营时间等政策合规风险。",
    "policy_redline_200m": "小学、幼儿园、中学、政府机构200m红线，命中后应高风险提示。",
}


def _nearest_distance(rows: list[dict], keywords: tuple[str, ...] = ()) -> Optional[float]:
    distances = []
    for row in rows or []:
        name = str(row.get("name") or row.get("type") or "")
        if keywords and not any(keyword in name for keyword in keywords):
            continue
        distance = _to_float(row.get("distance"))
        if distance is not None:
            distances.append(distance)
    return min(distances) if distances else None


def _distance_score(distance: Optional[float], breakpoints: tuple[tuple[float, float], ...]) -> Optional[float]:
    if distance is None:
        return None
    for limit, score in breakpoints:
        if distance <= limit:
            return score
    return breakpoints[-1][1] if breakpoints else None


def _field_presence_score(rows: list[dict], *fields: str) -> Optional[float]:
    included = _included_rows(rows)
    if not included:
        return None
    filled = 0
    total = 0
    for row in included:
        for field in fields:
            total += 1
            if row.get(field) not in (None, ""):
                filled += 1
    if total <= 0:
        return None
    return round(30 + 70 * filled / total, 1)


def _manual_count_score(rows: list[dict], field: str, unit_score: float = 12.0) -> Optional[float]:
    included = _included_rows(rows)
    if not included:
        return None
    total = sum((_to_float(row.get(field)) or 0) for row in included)
    return round(min(100, 45 + total * unit_score), 1)


def _find_manual_value(manual_data: dict, section: str, key: str) -> Optional[object]:
    section_data = manual_data.get(section) if isinstance(manual_data, dict) else None
    if isinstance(section_data, dict):
        return section_data.get(key)
    return manual_data.get(key) if isinstance(manual_data, dict) else None


def _factor_entry(
    sub_factor: str,
    weight: float,
    score: Optional[float],
    basis: str,
    source: str = "高德API",
    status: str = "scored",
) -> dict:
    if score is None:
        status = "missing" if status == "scored" else status
    return {
        "sub_factor": sub_factor,
        "name": FACTOR_LABELS.get(sub_factor, sub_factor),
        "description": FACTOR_DESCRIPTIONS.get(sub_factor, "自定义评分小类，按当前评分模型配置参与权重管理。"),
        "weight": round(float(weight or 0) * 100, 2),
        "score": round(float(score), 1) if score is not None else None,
        "basis": basis,
        "source": source,
        "status": status,
    }


def build_factor_breakdown(dimension_results: dict, weights: dict, manual_data: Optional[dict] = None) -> dict:
    """Build report-facing sub-factor details under each of the six dimensions."""
    manual_data = manual_data or {}
    breakdown = {dim: [] for dim in ["traffic", "competition", "population", "rent", "facility", "policy"]}
    factor_weights: dict[str, list[tuple[str, float]]] = {dim: [] for dim in breakdown}
    for key, value in weights.items():
        if "." not in str(key):
            continue
        dim, sub_factor = str(key).split(".", 1)
        if dim in factor_weights:
            factor_weights[dim].append((sub_factor, float(value or 0)))

    traffic = dimension_results.get("traffic") or {}
    competition = dimension_results.get("competition") or {}
    population = dimension_results.get("population") or {}
    rent = dimension_results.get("rent") or {}
    facility = dimension_results.get("facility") or {}
    policy = dimension_results.get("policy") or {}

    transit_pois = traffic.get("transit_pois") or []
    commercial_pois = traffic.get("commercial_pois") or []
    valid_competitors = competition.get("valid_competitor_pois") or []
    manual_competitors = _included_rows(manual_data.get("competitors"))
    market_capacity = competition.get("market_capacity") or {}
    education_pois = population.get("education_pois") or []
    residential_pois = population.get("residential_pois") or []
    office_pois = population.get("office_pois") or []
    food_pois = facility.get("food_pois") or []
    entertainment_pois = facility.get("entertainment_pois") or []
    convenience_pois = facility.get("convenience_pois") or []
    parking_pois = facility.get("parking_pois") or []
    manual_food = _included_rows(manual_data.get("food_places"))
    manual_night = _included_rows(manual_data.get("night_markets"))
    manual_entertainment = _included_rows(manual_data.get("entertainment_places"))
    manual_convenience = _included_rows(manual_data.get("convenience_stores"))

    def calc(dim: str, sub_factor: str) -> tuple[Optional[float], str, str, str]:
        if dim == "traffic":
            if sub_factor == "foot_traffic":
                score = min(100, (traffic.get("transit_count") or 0) * 10 + (traffic.get("commercial_count") or 0) * 18)
                return score, f"交通站点 {traffic.get('transit_count', 0)} 个，商业设施 {traffic.get('commercial_count', 0)} 个", "高德API", "scored"
            if sub_factor == "transit_accessibility":
                return min(100, (traffic.get("transit_count") or 0) * 15), f"高德识别公交/地铁/轻轨站 {traffic.get('transit_count', 0)} 个", "高德API", "scored"
            if sub_factor == "metro_distance":
                distance = _nearest_distance(transit_pois, ("地铁", "轻轨"))
                return _distance_score(distance, ((300, 95), (600, 80), (1000, 60), (999999, 40))), f"最近地铁/轻轨距离：{distance:.0f}m" if distance is not None else "高德底表未识别地铁/轻轨站", "高德API", "scored" if distance is not None else "missing"
            if sub_factor == "bus_distance":
                distance = _nearest_distance(transit_pois, ("公交",))
                return _distance_score(distance, ((150, 95), (300, 85), (600, 70), (999999, 45))), f"最近公交站距离：{distance:.0f}m" if distance is not None else "高德底表未识别公交站", "高德API", "scored" if distance is not None else "missing"
            return None, "需现场核验是否存在阻隔因素，当前高德 POI 未直接计算", "人工调研", "missing"
        if dim == "competition":
            if sub_factor == "competitor_count":
                return competition.get("score"), f"有效竞品 {competition.get('competitor_effective_count', competition.get('competitor_count_1500m', 0))} 家，待核验 {competition.get('competitor_candidate_count', 0)} 家", "高德API", "scored"
            if sub_factor == "competitor_distance":
                distance = _nearest_distance(valid_competitors)
                score = 90 if distance is None else _distance_score(distance, ((300, 30), (500, 45), (1000, 65), (999999, 82)))
                return score, f"最近有效竞品距离：{distance:.0f}m" if distance is not None else "评估半径内未识别有效竞品", "高德API", "scored"
            if sub_factor == "same_category_capacity":
                return market_capacity.get("score"), market_capacity.get("detail") or "缺少容量模型参数，待补充", market_capacity.get("source_label") or "人工调研", "scored" if market_capacity.get("can_calculate") else "missing"
            field_map = {
                "competitor_configuration": ("configuration", "机器配置/硬件"),
                "competitor_price": ("hourly_price", "小时价/套餐价"),
                "competitor_occupancy": ("occupancy_rate", "上座率"),
                "competitor_open_years": ("open_years", "开业年限"),
                "competitor_area": ("area_sqm", "面积"),
                "competitor_monthly_sales": ("monthly_sales", "月售/月营收"),
                "competitor_annual_sales": ("annual_sales", "年售/年营收"),
                "competitor_recharge": ("recharge_info", "充值活动"),
            }
            if sub_factor in field_map:
                field, label = field_map[sub_factor]
                score = _field_presence_score(manual_competitors, field)
                return score, f"人工确认竞品 {len(manual_competitors)} 家，{label}字段完整度参与判断" if score is not None else f"缺少竞品{label}，需调研补充", "人工调研/外部采集", "scored" if score is not None else "missing"
        if dim == "population":
            if sub_factor == "young_density":
                value = _find_manual_value(manual_data, "market_capacity_inputs", "resident_18_35")
                if value not in (None, ""):
                    return min(100, 45 + (_to_float(value) or 0) / 600), f"人工补充18-35岁有效人口：{value}", "人工调研/外部数据", "scored"
                return population.get("score"), "未接入真实年龄结构，暂用教育/住宅/办公 POI 作为客群代理", "高德API代理", "scored"
            if sub_factor == "university_nearby":
                return min(100, (population.get("education_weighted_count") or 0) * 35), population.get("education_filter_summary") or f"有效教育客群 {len(education_pois)} 条", "高德API", "scored"
            if sub_factor == "secondary_vocational_nearby":
                return min(100, (population.get("secondary_education_count") or 0) * 45), f"中职/技校/中学类客群 {population.get('secondary_education_count', 0)} 条", "高德API", "scored"
            if sub_factor == "resident_population":
                return min(100, (population.get("residential_count") or 0) * 5), f"住宅/公寓 POI {len(residential_pois)} 条", "高德API代理", "scored"
            if sub_factor == "floating_population":
                value = _find_manual_value(manual_data, "market_capacity_inputs", "floating_population")
                return (min(100, 45 + (_to_float(value) or 0) / 800) if value not in (None, "") else None), f"人工补充流动人口：{value}" if value not in (None, "") else f"办公/商业 POI 可作为弱代理：办公 {len(office_pois)} 条", "人工调研/外部数据", "scored" if value not in (None, "") else "missing"
            if sub_factor in {"age_18_24", "age_25_34"}:
                value = _find_manual_value(manual_data, "market_capacity_inputs", sub_factor)
                return (min(100, 40 + (_to_float(value) or 0)) if value not in (None, "") else None), f"人工补充{sub_factor}占比：{value}%" if value not in (None, "") else "年龄段占比暂未接入，需要人工/第三方人口数据补充", "人工调研/外部人口数据", "scored" if value not in (None, "") else "missing"
        if dim == "rent":
            if sub_factor == "rent_ratio":
                return rent.get("score"), rent.get("detail") or "待补充月租金和面积", rent.get("source_label") or ("用户录入" if rent.get("data_source") == "user" else "待调研"), "scored" if rent.get("data_source") != "missing" else "missing"
            property_map = {
                "area_sqm": ("property_conditions", "area_sqm", "面积"),
                "floor": ("property_conditions", "floor", "楼层"),
                "frontage_visibility": ("property_conditions", "frontage_visibility", "门头可见性"),
                "parking_convenience": ("property_conditions", "parking_convenience", "停车便利性"),
                "fire_safety": ("property_conditions", "fire_safety", "消防条件"),
                "property_restriction": ("property_conditions", "property_restriction", "物业限制"),
                "power_capacity": ("property_conditions", "power_capacity", "电力容量"),
                "hvac_exhaust": ("property_conditions", "hvac_exhaust", "空调/排烟"),
            }
            if sub_factor in property_map:
                section, field, label = property_map[sub_factor]
                value = _find_manual_value(manual_data, section, field)
                return (85 if value not in (None, "", "unknown") else None), f"{label}：{value}" if value not in (None, "", "unknown") else f"{label}待调研补充", "人工调研", "scored" if value not in (None, "", "unknown") else "missing"
        if dim == "facility":
            if sub_factor == "commercial_density":
                score = facility.get("score")
                return score, f"餐饮 {len(food_pois)} 家，娱乐 {len(entertainment_pois)} 个，便利店 {len(convenience_pois)} 家，停车场 {len(parking_pois)} 个", "高德API", "scored"
            if sub_factor == "night_market":
                score = _manual_count_score(manual_night, "stall_count", 1.5)
                return score, f"人工补充夜市摊 {len(manual_night)} 处", "人工调研/外部采集", "scored" if score is not None else "missing"
            if sub_factor in {"food_business_hours", "food_category", "food_open_years"}:
                field = {"food_business_hours": "business_hours", "food_category": "type", "food_open_years": "open_years"}[sub_factor]
                score = _field_presence_score(manual_food, field)
                return score, f"人工补充餐饮 {len(manual_food)} 家，字段 {field} 完整度参与判断" if score is not None else "餐饮底表已生成，需人工补充营业时间/品类/年限", "人工调研/高德底表", "scored" if score is not None else "missing"
            entertainment_keywords = {
                "ktv": ("KTV", "ktv"),
                "bar": ("酒吧",),
                "billiards": ("台球",),
                "escape_room": ("密室", "剧本杀"),
                "cinema": ("影院", "电影院"),
            }
            if sub_factor in entertainment_keywords:
                count = sum(1 for row in (entertainment_pois + manual_entertainment) if any(k.lower() in str(row.get("name") or row.get("type") or "").lower() for k in entertainment_keywords[sub_factor]))
                return min(100, 45 + count * 18), f"高德/人工识别相关配套 {count} 个", "高德API+人工调研", "scored"
            if sub_factor == "convenience_24h":
                score = _field_presence_score(manual_convenience, "is_24h", "business_hours")
                return score, f"便利店底表 {len(convenience_pois)} 家，人工补充 {len(manual_convenience)} 家" if score is not None else "需人工确认是否24小时营业", "高德API+人工调研", "scored" if score is not None else "missing"
            if sub_factor in {"relocation_housing", "apartment"}:
                keyword = "回迁" if sub_factor == "relocation_housing" else "公寓"
                count = sum(1 for row in residential_pois if keyword in str(row.get("name") or row.get("type") or ""))
                return min(100, 45 + count * 12), f"住宅办公底表中识别 {keyword} 相关 {count} 条", "高德API代理", "scored"
        if dim == "policy":
            if sub_factor == "policy_redline_200m":
                count = policy.get("policy_redline_count") or 0
                return (25 if count else 90), policy.get("policy_redline_summary") or f"200m政策红线命中 {count} 个", "高德API", "scored"
            if sub_factor == "policy_risk":
                return policy.get("score"), policy.get("detail") or "政策风险待补充", policy.get("source_label") or "高德API+人工调研", "scored"
        return None, "当前模型已配置该子因子，但本次报告暂无可计算数据", "待调研", "missing"

    for dim, factors in factor_weights.items():
        for sub_factor, weight in sorted(factors, key=lambda item: (item[1] <= 0, item[0])):
            score, basis, source, status = calc(dim, sub_factor)
            breakdown[dim].append(_factor_entry(sub_factor, weight, score, basis, source, status))
    return breakdown


def detect_data_quality_issues(address: str, dimension_results: dict) -> list[dict]:
    issues = []
    policy = dimension_results.get("policy") or {}
    redline_count = policy.get("policy_redline_count")
    if isinstance(redline_count, int) and redline_count > 0:
        issues.append({
            "source_type": "external_api",
            "issue_type": "policy_redline_distance",
            "severity": "error",
            "title": "政策红线距离不满足要求",
            "description": f"{address} 200m 内存在小学、幼儿园、中学或政府机构等政策红线 POI {redline_count} 个，建议视为高风险并人工复核。",
            "payload": {
                "dimension": "policy",
                "field": "policy_redline_count",
                "value": redline_count,
                "threshold": 0,
                "radius_m": 200,
                "redline_pois": policy.get("policy_redline_pois", []),
            },
        })
    competition = dimension_results.get("competition") or {}
    capacity = competition.get("market_capacity") or {}
    if capacity and not capacity.get("can_calculate"):
        missing = capacity.get("missing_fields") or []
        issues.append({
            "source_type": "manual_input",
            "issue_type": "market_capacity_missing_fields",
            "severity": "warning",
            "title": "商圈容量模型缺少关键参数",
            "description": f"缺少 {', '.join(missing)}，暂不能判断该区域还能容纳几家电竞馆。",
            "payload": {"dimension": "competition", "missing_fields": missing},
        })
    population = dimension_results.get("population") or {}
    university_count = population.get("university_count")
    education_effective_count = population.get("education_effective_count")
    effective_count = education_effective_count if isinstance(education_effective_count, int) else university_count
    if isinstance(effective_count, int) and effective_count > 30:
        issues.append({
            "source_type": "external_api",
            "issue_type": "poi_overmatch_university",
            "severity": "warning",
            "title": "教育客群 POI 数量疑似异常",
            "description": f"{address} 3km 内有效教育客群 POI 为 {effective_count} 条，超过合理阈值 30 条，建议人工核验。",
            "payload": {"dimension": "population", "field": "education_effective_count", "value": effective_count, "threshold": 30},
        })
    university_api_total = population.get("university_api_total_count")
    excluded_education_count = population.get("excluded_education_count")
    if isinstance(university_api_total, int) and isinstance(effective_count, int) and university_api_total > 15 and university_api_total > effective_count:
        issues.append({
            "source_type": "external_api",
            "issue_type": "poi_raw_count_overmatch_university",
            "severity": "warning",
            "title": "高德教育 POI 原始匹配数疑似过匹配",
            "description": f"{address} 3km 内高德原始匹配教育相关 POI {university_api_total} 条，清洗后计入 {effective_count} 条，排除 {excluded_education_count or 0} 条。建议人工核验关键词是否过匹配。",
            "payload": {
                "dimension": "population",
                "field": "university_api_total_count",
                "value": university_api_total,
                "deduped_value": effective_count,
                "excluded_value": excluded_education_count or 0,
                "threshold": 15,
            },
        })
    for dim, data in dimension_results.items():
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if key.endswith("_count") and isinstance(value, int) and value > 200:
                issues.append({
                    "source_type": "external_api",
                    "issue_type": "poi_count_outlier",
                    "severity": "warning",
                    "title": "POI 数量疑似异常",
                    "description": f"{dim}.{key} 返回 {value}，数量过高，建议人工核验。",
                    "payload": {"dimension": dim, "field": key, "value": value, "threshold": 200},
                })
    return issues


def persist_evaluation_record(
    db: Session,
    tenant_id: int,
    created_by: Optional[int],
    radius: int,
    final_result: dict,
    normalized_weights: dict,
    llm_report: str,
    rag_evidence: list,
    model_version: Optional[ScoringModelVersion],
    quality_issues: list[dict],
) -> Optional[int]:
    try:
        record = EvaluationRecord(
            tenant_id=tenant_id,
            model_version_id=model_version.id if model_version else None,
            address=final_result.get("address", ""),
            longitude=final_result.get("longitude"),
            latitude=final_result.get("latitude"),
            radius=radius,
            total_score=final_result.get("total_score"),
            grade=final_result.get("grade"),
            grade_label=final_result.get("grade_label"),
            dimensions=final_result.get("dimensions"),
            normalized_weights=normalized_weights,
            data_quality=final_result.get("data_quality"),
            manual_data=final_result.get("manual_data"),
            llm_report=llm_report,
            rag_evidence=rag_evidence,
            created_by=created_by,
        )
        db.add(record)
        db.flush()
        for issue in quality_issues:
            db.add(DataQualityIssue(
                tenant_id=tenant_id,
                evaluation_id=record.id,
                source_type=issue.get("source_type", "external_api"),
                source_id=record.id,
                issue_type=issue.get("issue_type", "unknown"),
                severity=issue.get("severity", "warning"),
                title=issue.get("title", "数据质量问题"),
                description=issue.get("description"),
                payload=issue.get("payload"),
                created_by=created_by,
            ))
        db.commit()
        return record.id
    except Exception as e:
        logger.warning(f"评估记录落库失败，不影响评估结果: {e}")
        db.rollback()
        return None


async def score_traffic(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    """
    交通与人流评分
    - 周边公交/地铁站数量
    - 周边商业综合体/购物中心数量（间接反映人流）
    """
    # 公交/地铁站
    transit_result = await search_poi_around(
        longitude, latitude,
        keywords="地铁站|公交站|轻轨站",
        radius=radius,
        api_key=api_key
    )
    transit_count = int(transit_result.get("count", 0)) if transit_result.get("status") == "1" else 0

    # 商业综合体（人流指标）
    commercial_result = await search_poi_around(
        longitude, latitude,
        keywords="购物中心|商业广场|万达|万象城|吾悦广场",
        radius=radius,
        api_key=api_key
    )
    commercial_count = int(commercial_result.get("count", 0)) if commercial_result.get("status") == "1" else 0

    # 评分逻辑
    transit_score = min(100, transit_count * 15)  # 每个站15分，最高100
    commercial_score = min(100, commercial_count * 30)  # 每个商业体30分

    score = transit_score * 0.6 + commercial_score * 0.4

    return {
        "score": round(score, 1),
        "transit_count": transit_count,
        "commercial_count": commercial_count,
        "detail": f"周边 {radius}m 内公交/地铁站 {transit_count} 个，商业综合体 {commercial_count} 个"
    }


async def score_competition(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    """
    竞品分析评分
    - 竞品数量越少，得分越高
    - 最近竞品距离越远，得分越高
    """
    competitor_count = await get_competitor_count(longitude, latitude, radius, api_key)

    # 搜索最近竞品距离
    nearby_result = await search_poi_around(
        longitude, latitude,
        keywords="网吧|电竞馆|电竞酒店|游戏厅",
        radius=500,  # 500m 内
        api_key=api_key
    )
    nearest_count_500m = int(nearby_result.get("count", 0)) if nearby_result.get("status") == "1" else 0

    # 评分逻辑（竞品越少越好）
    if competitor_count == 0:
        competition_score = 100
    elif competitor_count <= 2:
        competition_score = 80
    elif competitor_count <= 5:
        competition_score = 60
    elif competitor_count <= 10:
        competition_score = 40
    else:
        competition_score = 20

    # 500m 内有竞品额外扣分
    if nearest_count_500m > 0:
        competition_score = max(0, competition_score - nearest_count_500m * 15)

    return {
        "score": round(competition_score, 1),
        "competitor_count_1500m": competitor_count,
        "competitor_count_500m": nearest_count_500m,
        "detail": f"周边 {radius}m 内竞品 {competitor_count} 家，500m 内竞品 {nearest_count_500m} 家"
    }


async def score_population(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    """
    目标客群评分
    - 周边高校数量（18-25岁核心客群）
    - 周边住宅小区密度
    - 周边写字楼/办公区（25-35岁客群）
    """
    # 高校
    university_result = await search_poi_around(
        longitude, latitude,
        keywords="大学|学院|职业技术学院|高校",
        radius=3000,  # 高校搜索半径更大
        api_key=api_key
    )
    university_count = int(university_result.get("count", 0)) if university_result.get("status") == "1" else 0

    # 住宅小区
    residential_result = await search_poi_around(
        longitude, latitude,
        keywords="住宅小区|居民区|公寓",
        radius=radius,
        api_key=api_key
    )
    residential_count = int(residential_result.get("count", 0)) if residential_result.get("status") == "1" else 0

    # 写字楼/办公
    office_result = await search_poi_around(
        longitude, latitude,
        keywords="写字楼|办公楼|科技园|产业园",
        radius=radius,
        api_key=api_key
    )
    office_count = int(office_result.get("count", 0)) if office_result.get("status") == "1" else 0

    # 评分逻辑
    university_score = min(100, university_count * 40)  # 大学权重最高
    residential_score = min(100, residential_count * 5)
    office_score = min(100, office_count * 10)

    score = university_score * 0.5 + residential_score * 0.3 + office_score * 0.2

    return {
        "score": round(score, 1),
        "university_count": university_count,
        "residential_count": residential_count,
        "office_count": office_count,
        "detail": f"3km内高校 {university_count} 所，周边住宅 {residential_count} 个，写字楼 {office_count} 栋"
    }


async def score_facility(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    """
    配套设施评分
    - 餐饮（客群停留时间）
    - 便利店/超市
    - 停车场
    """
    # 餐饮
    food_result = await search_poi_around(
        longitude, latitude,
        keywords="餐厅|快餐|外卖|美食",
        radius=radius,
        api_key=api_key
    )
    food_count = int(food_result.get("count", 0)) if food_result.get("status") == "1" else 0

    # 便利店
    convenience_result = await search_poi_around(
        longitude, latitude,
        keywords="便利店|超市|711|全家|罗森",
        radius=500,
        api_key=api_key
    )
    convenience_count = int(convenience_result.get("count", 0)) if convenience_result.get("status") == "1" else 0

    # 停车场
    parking_result = await search_poi_around(
        longitude, latitude,
        keywords="停车场|停车库",
        radius=radius,
        api_key=api_key
    )
    parking_count = int(parking_result.get("count", 0)) if parking_result.get("status") == "1" else 0

    score = (
        min(100, food_count * 3) * 0.4 +
        min(100, convenience_count * 20) * 0.3 +
        min(100, parking_count * 15) * 0.3
    )

    return {
        "score": round(score, 1),
        "food_count": food_count,
        "convenience_count": convenience_count,
        "parking_count": parking_count,
        "detail": f"周边餐饮 {food_count} 家，便利店 {convenience_count} 家，停车场 {parking_count} 个"
    }


def _to_float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    num = _to_float(value)
    return int(num) if num is not None else None


def _nested_manual_value(manual_data: dict, group: str, key: str, *fallback_keys):
    nested = manual_data.get(group) if isinstance(manual_data, dict) else None
    if isinstance(nested, dict):
        value = nested.get(key)
        if value not in (None, ""):
            return value
    for fallback_key in fallback_keys:
        value = manual_data.get(fallback_key) if isinstance(manual_data, dict) else None
        if value not in (None, ""):
            return value
    return None


def _included_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if (
            isinstance(row, dict)
            and row.get("include", True) is not False
            and row.get("status") not in {"excluded", "pending_review"}
        )
    ]


def _excluded_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, dict) and (row.get("include") is False or row.get("status") == "excluded")
    ]


def _research_status_rows(rows, status: str, source: str = "高德API") -> list[dict]:
    if not isinstance(rows, list):
        return []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["status"] = item.get("status") or status
        raw_source = item.get("source") or item.get("data_source") or source
        item["source"] = "高德API" if raw_source in {"amap", "api"} else raw_source
        item["data_source"] = item.get("data_source") or item["source"]
        item["include"] = False if item["status"] in {"excluded", "pending_review"} else item.get("include", True)
        if item.get("scope") and not item.get("scope_label"):
            item["scope_label"] = "核心范围" if item["scope"] == "core" else ("扩展范围" if item["scope"] == "extended" else item["scope"])
        normalized.append(item)
    return normalized


def _poi_distance_int(row: dict) -> Optional[int]:
    if not isinstance(row, dict):
        return None
    value = row.get("distance")
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace("m", "").strip()))
    except (TypeError, ValueError):
        return None


def _with_scope(rows: list[dict], scope: str) -> list[dict]:
    scoped = []
    label = "核心范围" if scope == "core" else ("扩展范围" if scope == "extended" else scope)
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["scope"] = scope
        item["scope_label"] = label
        scoped.append(item)
    return scoped


def _split_rows_by_radius(rows: list[dict], radius: int) -> tuple[list[dict], list[dict]]:
    core, extended = [], []
    for row in rows or []:
        distance = _poi_distance_int(row)
        if distance is not None and distance <= radius:
            core.append(row)
        else:
            extended.append(row)
    return _with_scope(core, "core"), _with_scope(extended, "extended")


def _poi_audit_entry(
    key: str,
    label: str,
    keywords: str,
    raw_count: int,
    deduped_count: int,
    included_count: int = 0,
    pending_count: int = 0,
    excluded_count: int = 0,
    displayed_count: Optional[int] = None,
    query_status: Optional[str] = None,
    query_info: Optional[str] = None,
    query_infocode: Optional[str] = None,
) -> dict:
    shown = included_count + pending_count + excluded_count if displayed_count is None else displayed_count
    entry = {
        "key": key,
        "label": label,
        "keywords": keywords,
        "raw_count": raw_count or 0,
        "deduped_count": deduped_count or 0,
        "included_count": included_count or 0,
        "pending_count": pending_count or 0,
        "excluded_count": excluded_count or 0,
        "displayed_count": shown or 0,
        "is_truncated": bool(deduped_count and shown < deduped_count),
    }
    if query_status is not None:
        entry.update({
            "query_status": str(query_status),
            "query_info": query_info or "",
            "query_infocode": query_infocode or "",
        })
    return entry


def _haversine_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_m = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _manual_positive_score(value, enabled_score: float = 85.0, disabled_score: float = 45.0) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"yes", "true", "1", "有", "是", "large", "medium"}:
            return enabled_score
        if value in {"no", "false", "0", "无", "否"}:
            return disabled_score
    return enabled_score if bool(value) else disabled_score


def _load_local_competitors(db: Session, tenant_id: int, longitude: float, latitude: float, radius: int) -> list[dict]:
    rows = db.query(CompetitorProfile).filter(
        CompetitorProfile.tenant_id == tenant_id,
        CompetitorProfile.is_active == True,
        CompetitorProfile.longitude.isnot(None),
        CompetitorProfile.latitude.isnot(None),
    ).all()
    items = []
    for row in rows:
        distance = _haversine_distance_m(longitude, latitude, float(row.longitude), float(row.latitude))
        if distance <= radius:
            items.append({
                "id": row.id,
                "name": row.name,
                "address": row.address,
                "distance": int(round(distance)),
                "configuration": row.configuration,
                "machine_count": row.machine_count,
                "area_sqm": row.area_sqm,
                "hourly_price": row.hourly_price,
                "package_price": row.package_price,
                "occupancy_rate": row.occupancy_rate,
                "open_years": row.open_years,
                "monthly_sales": row.monthly_sales,
                "annual_sales": row.annual_sales,
                "recharge_info": row.recharge_info,
                "data_source": row.data_source,
                "confidence": row.confidence,
                "classification_label": "本地竞品档案",
                "classification_reason": "用户沉淀的竞品档案，优先用于竞品趋势和容量判断",
            })
    return sorted(items, key=lambda item: item["distance"])


def _normalize_manual_competitors(items) -> list[dict]:
    competitors = []
    if not isinstance(items, list):
        return competitors
    for idx, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        if item.get("include") is False or item.get("status") in {"excluded", "pending_review"}:
            continue
        competitor = {
            "id": item.get("id") or f"manual-{idx + 1}",
            "name": item.get("name"),
            "address": item.get("address"),
            "distance": _to_int(item.get("distance")),
            "configuration": item.get("configuration"),
            "machine_count": _to_int(item.get("machine_count")),
            "area_sqm": _to_float(item.get("area_sqm")),
            "hourly_price": _to_float(item.get("hourly_price")),
            "package_price": _to_float(item.get("package_price")),
            "occupancy_rate": _to_float(item.get("occupancy_rate")),
            "open_years": _to_float(item.get("open_years")),
            "monthly_sales": _to_float(item.get("monthly_sales")),
            "annual_sales": _to_float(item.get("annual_sales")),
            "recharge_info": item.get("recharge_info"),
            "data_source": item.get("data_source") or item.get("source") or "manual",
            "confidence": _to_float(item.get("confidence")) or 0.8,
            "classification_label": "本次人工调研",
            "classification_reason": "用户在本次评估中补充的竞品真实调研数据",
        }
        competitors.append(competitor)
    return competitors


def _build_market_capacity(
    competition_data: dict,
    population_data: dict,
    manual_data: dict,
    allow_mock_data: bool,
) -> dict:
    resident_18_35 = _to_float(_nested_manual_value(
        manual_data, "market_capacity_inputs", "effective_population_18_35",
        "effective_population_18_35", "resident_population_18_35"
    ))
    floating_population = _to_float(_nested_manual_value(manual_data, "market_capacity_inputs", "floating_population", "floating_population"))
    conversion_rate_pct = _to_float(_nested_manual_value(manual_data, "market_capacity_inputs", "conversion_rate_pct", "conversion_rate_pct"))
    monthly_frequency = _to_float(_nested_manual_value(manual_data, "market_capacity_inputs", "monthly_frequency", "monthly_frequency"))
    avg_spend = _to_float(_nested_manual_value(manual_data, "market_capacity_inputs", "avg_spend", "avg_spend"))
    healthy_monthly_revenue = _to_float(_nested_manual_value(manual_data, "market_capacity_inputs", "healthy_monthly_revenue", "healthy_monthly_revenue"))

    missing = []
    if resident_18_35 is None:
        missing.append("18-35岁有效常住人口")
    if floating_population is None:
        missing.append("流动人口")
    if conversion_rate_pct is None:
        missing.append("转化率")
    if monthly_frequency is None:
        missing.append("月均消费频次")
    if avg_spend is None:
        missing.append("客单价")
    if healthy_monthly_revenue is None:
        missing.append("单店健康月营收")

    used_estimation = False
    if missing and allow_mock_data:
        used_estimation = True
        resident_18_35 = resident_18_35 if resident_18_35 is not None else max(3000.0, float(population_data.get("education_weighted_count") or 0) * 1800)
        floating_population = floating_population if floating_population is not None else 0.0
        conversion_rate_pct = conversion_rate_pct if conversion_rate_pct is not None else 4.0
        monthly_frequency = monthly_frequency if monthly_frequency is not None else 2.0
        avg_spend = avg_spend if avg_spend is not None else 35.0
        healthy_monthly_revenue = healthy_monthly_revenue if healthy_monthly_revenue is not None else 90000.0

    can_calculate = not missing or allow_mock_data
    if not can_calculate:
        return {
            "can_calculate": False,
            "score": None,
            "missing_fields": missing,
            "detail": f"缺少 {', '.join(missing)}，暂不能计算商圈容量",
            "data_source": "missing",
            "source_label": "待人工补充",
        }

    effective_people = (resident_18_35 or 0) + (floating_population or 0)
    monthly_market_size = effective_people * ((conversion_rate_pct or 0) / 100) * (monthly_frequency or 0) * (avg_spend or 0)
    supportable_store_count = monthly_market_size / healthy_monthly_revenue if healthy_monthly_revenue else 0
    existing_supply = (
        len(competition_data.get("valid_competitor_pois") or [])
        + len(competition_data.get("local_competitor_profiles") or [])
        + len(competition_data.get("manual_competitors") or [])
    )
    remaining_capacity = supportable_store_count - existing_supply
    if remaining_capacity >= 1.2:
        score = 88.0
    elif remaining_capacity >= 0.5:
        score = 72.0
    elif remaining_capacity >= 0:
        score = 55.0
    else:
        score = 35.0

    return {
        "can_calculate": True,
        "score": round(score, 1),
        "effective_people": round(effective_people, 1),
        "conversion_rate_pct": conversion_rate_pct,
        "monthly_frequency": monthly_frequency,
        "avg_spend": avg_spend,
        "healthy_monthly_revenue": healthy_monthly_revenue,
        "monthly_market_size": round(monthly_market_size, 1),
        "supportable_store_count": round(supportable_store_count, 2),
        "existing_supply_count": existing_supply,
        "remaining_capacity": round(remaining_capacity, 2),
        "missing_fields": missing,
        "data_source": "estimation" if used_estimation else "user",
        "source_label": "用户补充 + 授权估算" if used_estimation else "用户补充真实经营假设",
        "detail": f"理论月市场规模约 {monthly_market_size:.0f} 元，可支撑 {supportable_store_count:.2f} 家健康门店；扣除已识别竞品供给 {existing_supply} 家，剩余容量 {remaining_capacity:.2f} 家",
    }


def _apply_competitor_research(
    competition_data: dict,
    population_data: dict,
    manual_data: dict,
    local_competitors: list[dict],
    allow_mock_data: bool,
) -> dict:
    manual_competitors = _normalize_manual_competitors(manual_data.get("competitors"))
    if local_competitors:
        competition_data["local_competitor_profiles"] = local_competitors[:50]
    if manual_competitors:
        competition_data["manual_competitors"] = manual_competitors[:50]

    confirmed_count = len(local_competitors) + len(manual_competitors)
    if confirmed_count:
        competition_data["confirmed_competitor_count"] = confirmed_count
        competition_data["detail"] += f"；本地/本次人工确认竞品 {confirmed_count} 家"
        competition_data["source_label"] = "高德地图 API + 本地竞品档案/人工调研"

    capacity = _build_market_capacity(competition_data, population_data, manual_data, allow_mock_data)
    competition_data["market_capacity"] = capacity
    if capacity.get("can_calculate"):
        competition_data["score"] = round(competition_data.get("score", 60) * 0.7 + capacity["score"] * 0.3, 1)
        competition_data["detail"] += f"；商圈容量：{capacity['detail']}"
    else:
        competition_data.setdefault("missing_fields", []).extend(capacity.get("missing_fields") or [])
        competition_data["detail"] += f"；商圈容量暂未计算：{capacity['detail']}"
    return competition_data


def _apply_manual_facility_data(facility_data: dict, manual_data: dict) -> dict:
    scores = []
    notes = []
    food_places = _included_rows(manual_data.get("food_places"))
    night_markets = _included_rows(manual_data.get("night_markets"))
    entertainment_places = _included_rows(manual_data.get("entertainment_places"))
    convenience_stores = _included_rows(manual_data.get("convenience_stores"))

    late_food_count = sum(1 for row in food_places if row.get("late_night") or "凌晨" in str(row.get("business_hours") or ""))
    convenience_24h_count = sum(1 for row in convenience_stores if row.get("is_24h") or "24" in str(row.get("business_hours") or ""))
    if night_markets:
        level_score = min(100, 55 + sum((_to_float(row.get("stall_count")) or 0) for row in night_markets) * 1.5 + len(night_markets) * 8)
        scores.append(level_score)
        notes.append(f"夜市摊：{len(night_markets)} 处")
    if late_food_count:
        scores.append(min(100, 45 + late_food_count * 10))
        notes.append(f"凌晨餐饮：{late_food_count} 家")
    if entertainment_places:
        scores.append(min(100, 45 + len(entertainment_places) * 10))
        notes.append(f"娱乐业态：{len(entertainment_places)} 家")
    if convenience_24h_count:
        scores.append(min(100, 50 + convenience_24h_count * 12))
        notes.append(f"24小时便利店：{convenience_24h_count} 家")

    field_map = [
        ("night_market_level", "夜市摊", {"large": 95, "medium": 80, "small": 62, "none": 35}),
        ("late_night_food_count", "凌晨餐饮", None),
        ("entertainment_count", "娱乐业态", None),
        ("convenience_24h_count", "24小时便利店", None),
    ]
    for field, label, enum_scores in field_map:
        value = manual_data.get(field)
        if value in (None, ""):
            continue
        if enum_scores:
            score = enum_scores.get(str(value), 60)
            notes.append(f"{label}：{value}")
        else:
            count = _to_float(value) or 0
            score = min(100, 45 + count * 12)
            notes.append(f"{label}：{count:.0f}")
        scores.append(score)

    for field, label in [
        ("has_ktv_nearby", "KTV"),
        ("has_bar_nearby", "酒吧"),
        ("has_billiards_nearby", "台球"),
        ("has_cinema_nearby", "电影院"),
    ]:
        score = _manual_positive_score(manual_data.get(field))
        if score is not None:
            scores.append(score)
            notes.append(f"{label}：{'有' if score >= 80 else '无'}")

    if scores:
        manual_score = sum(scores) / len(scores)
        facility_data["score"] = round(facility_data.get("score", 60) * 0.65 + manual_score * 0.35, 1)
        facility_data["manual_facility_data"] = {k: v for k, v in manual_data.items() if k in {
            "night_market_level", "late_night_food_count", "entertainment_count", "convenience_24h_count",
            "has_ktv_nearby", "has_bar_nearby", "has_billiards_nearby", "has_cinema_nearby",
        }}
        facility_data["manual_facility_tables"] = {
            "food_places": food_places,
            "night_markets": night_markets,
            "entertainment_places": entertainment_places,
            "convenience_stores": convenience_stores,
        }
        facility_data["detail"] += f"；人工补充配套：{'；'.join(notes)}"
        facility_data["source_label"] = "高德地图 API + 用户补充配套"
    return facility_data


def _apply_property_conditions(rent_data: dict, manual_data: dict) -> dict:
    scores = []
    notes = []
    floor = _to_int(_nested_manual_value(manual_data, "property_conditions", "floor", "floor"))
    if floor is not None:
        if floor <= 2:
            scores.append(88)
        elif floor <= 4:
            scores.append(68)
        else:
            scores.append(45)
        notes.append(f"楼层 {floor} 层")
    for field, label in [
        ("frontage_visibility", "门头可见性"),
        ("parking_convenience", "停车便利性"),
        ("fire_safety_ready", "消防条件"),
        ("power_capacity_ready", "电力容量"),
        ("hvac_ready", "空调/排烟"),
    ]:
        value = _nested_manual_value(manual_data, "property_conditions", field, field)
        if value in (None, ""):
            continue
        if field == "frontage_visibility":
            score_map = {"high": 90, "medium": 70, "low": 45}
            score = score_map.get(str(value), 60)
            label_value = {"high": "高", "medium": "中", "low": "低"}.get(str(value), str(value))
        else:
            score = _manual_positive_score(value, enabled_score=85, disabled_score=35)
            label_value = "满足" if score and score >= 80 else "不满足"
        scores.append(score or 60)
        notes.append(f"{label}{label_value}")
    restriction = str(_nested_manual_value(manual_data, "property_conditions", "property_restriction", "property_restriction") or "").strip()
    if restriction:
        scores.append(35)
        notes.append(f"物业限制：{restriction}")
    if scores:
        property_score = sum(scores) / len(scores)
        rent_data["score"] = round(rent_data.get("score", 60) * 0.65 + property_score * 0.35, 1)
        property_conditions = manual_data.get("property_conditions") if isinstance(manual_data.get("property_conditions"), dict) else {}
        rent_data["property_conditions"] = {**property_conditions, **{k: v for k, v in manual_data.items() if k in {
            "floor", "frontage_visibility", "parking_convenience", "fire_safety_ready",
            "property_restriction", "power_capacity_ready", "hvac_ready",
        }}}
        rent_data["detail"] += f"；物业条件：{'；'.join(notes)}"
        rent_data["source_label"] = "用户补充租金/物业真实数据"
    return rent_data


def _build_data_quality(amap_key: Optional[str], dimension_results: dict) -> dict:
    items = [
        {
            "key": "geo_poi",
            "name": "地理编码与周边 POI",
            "status": "real" if amap_key else "simulation",
            "source": "高德地图 API" if amap_key else "模拟数据",
        }
    ]
    for key, name in {
        "traffic": "交通与人流",
        "competition": "竞品分布",
        "population": "目标客群",
        "facility": "配套设施",
        "rent": "租金成本",
        "policy": "政策合规",
    }.items():
        data = dimension_results.get(key, {})
        source = data.get("data_source") or ("simulation" if data.get("is_simulated") else "api")
        source_label = data.get("source_label") or ("用户提供" if source == "user" else ("模拟数据" if source == "simulation" else "外部 API"))
        status = "simulation" if source == "simulation" else ("missing" if source == "missing" or "missing" in str(source) else "real")
        items.append({
            "key": key,
            "name": name,
            "status": status,
            "source": source_label,
            "detail": data.get("detail", ""),
        })
    return {
        "has_simulation": any(item["status"] == "simulation" for item in items),
        "has_missing": any(item["status"] == "missing" for item in items),
        "items": items,
    }


def build_research_required_fields(manual_data: Optional[dict]) -> dict:
    manual_data = manual_data or {}
    checks = [
        ("monthly_rent", "月租金（元/月）", _nested_manual_value(manual_data, "property_conditions", "monthly_rent", "monthly_rent")),
        ("area_sqm", "面积（㎡）", _nested_manual_value(manual_data, "property_conditions", "area_sqm", "area_sqm")),
        ("floor", "楼层（层）", _nested_manual_value(manual_data, "property_conditions", "floor", "floor")),
        ("frontage_visibility", "门头可见性", _nested_manual_value(manual_data, "property_conditions", "frontage_visibility", "frontage_visibility")),
        ("fire_safety_ready", "消防条件", _nested_manual_value(manual_data, "property_conditions", "fire_safety_ready", "fire_safety_ready")),
        ("property_restriction", "物业限制", _nested_manual_value(manual_data, "property_conditions", "property_restriction", "property_restriction")),
        ("policy_risk", "政策风险等级", manual_data.get("policy_risk")),
        ("effective_population_18_35", "18-35岁有效人口", _nested_manual_value(manual_data, "market_capacity_inputs", "effective_population_18_35", "effective_population_18_35")),
        ("conversion_rate_pct", "转化率（%）", _nested_manual_value(manual_data, "market_capacity_inputs", "conversion_rate_pct", "conversion_rate_pct")),
        ("monthly_frequency", "月均消费频次", _nested_manual_value(manual_data, "market_capacity_inputs", "monthly_frequency", "monthly_frequency")),
        ("avg_spend", "客单价（元）", _nested_manual_value(manual_data, "market_capacity_inputs", "avg_spend", "avg_spend")),
        ("healthy_monthly_revenue", "单店健康月营收（元/月）", _nested_manual_value(manual_data, "market_capacity_inputs", "healthy_monthly_revenue", "healthy_monthly_revenue")),
        ("competitor_research", "竞品配置/价位/上座率", _included_rows(manual_data.get("competitors"))),
        ("night_economy", "夜市/凌晨餐饮/24h便利店", (
            _included_rows(manual_data.get("night_markets"))
            or _included_rows(manual_data.get("food_places"))
            or _included_rows(manual_data.get("convenience_stores"))
        )),
    ]
    items = []
    for key, label, value in checks:
        ready = bool(value) or value is False
        items.append({
            "key": key,
            "label": label,
            "ready": ready,
            "status": "已补充" if ready else "缺失/待调研",
        })
    ready_count = sum(1 for item in items if item["ready"])
    return {
        "items": items,
        "missing": [item for item in items if not item["ready"]],
        "completion_rate": round(ready_count / len(items) * 100, 1) if items else 100.0,
    }


def build_research_tables(dimension_results: Optional[dict], manual_data: Optional[dict]) -> dict:
    dimension_results = dimension_results or {}
    manual_data = manual_data or {}
    competition = dimension_results.get("competition") or {}
    facility = dimension_results.get("facility") or {}
    population = dimension_results.get("population") or {}
    policy = dimension_results.get("policy") or {}
    included_manual_competitors = _research_status_rows(_included_rows(manual_data.get("competitors")), "manual_added", "人工调研")
    included_food = _research_status_rows(_included_rows(manual_data.get("food_places")), "manual_added", "人工调研")
    included_night_markets = _research_status_rows(_included_rows(manual_data.get("night_markets")), "manual_added", "人工调研")
    included_entertainment = _research_status_rows(_included_rows(manual_data.get("entertainment_places")), "manual_added", "人工调研")
    included_convenience = _research_status_rows(_included_rows(manual_data.get("convenience_stores")), "manual_added", "人工调研")
    return {
        "confirmed": {
            "competitors": {
                "amap": _research_status_rows(
                    competition.get("valid_competitor_pois") or competition.get("competitor_pois_1500m") or [],
                    "included",
                    "高德API",
                ),
                "pending": _research_status_rows(competition.get("competitor_candidate_pois") or [], "pending_review", "高德API"),
                "manual": included_manual_competitors,
            },
            "food_places": {
                "amap": _research_status_rows(facility.get("food_pois") or [], "included", "高德API"),
                "manual": included_food,
            },
            "night_markets": {
                "amap": [],
                "manual": included_night_markets,
            },
            "entertainment_places": {
                "amap": _research_status_rows(facility.get("entertainment_pois") or [], "included", "高德API"),
                "pending": _research_status_rows(facility.get("entertainment_candidate_pois") or [], "pending_review", "高德API"),
                "manual": included_entertainment,
            },
            "convenience_stores": {
                "amap": _research_status_rows(facility.get("convenience_pois") or [], "included", "高德API"),
                "manual": included_convenience,
            },
            "parking_places": {
                "amap": _research_status_rows(facility.get("parking_pois") or [], "included", "高德API"),
                "manual": [],
            },
            "education": {
                "amap": _research_status_rows(population.get("education_pois") or population.get("university_pois") or [], "included", "高德API"),
                "pending": _research_status_rows(population.get("education_candidate_pois") or [], "pending_review", "高德API"),
                "manual": [],
            },
            "policy_redline": {
                "amap": _research_status_rows(policy.get("policy_redline_pois") or [], "included", "高德API"),
                "manual": [],
            },
        },
        "excluded": {
            "competitors": _research_status_rows(
                (competition.get("excluded_competitor_pois") or []) + _excluded_rows(manual_data.get("competitors")),
                "excluded",
                "高德API",
            ),
            "food_places": _research_status_rows(_excluded_rows(manual_data.get("food_places")), "excluded", "人工调研"),
            "night_markets": _research_status_rows(_excluded_rows(manual_data.get("night_markets")), "excluded", "人工调研"),
            "entertainment_places": _research_status_rows(
                (facility.get("excluded_entertainment_pois") or []) + _excluded_rows(manual_data.get("entertainment_places")),
                "excluded",
                "高德API",
            ),
            "convenience_stores": _research_status_rows(_excluded_rows(manual_data.get("convenience_stores")), "excluded", "人工调研"),
            "education": _research_status_rows(population.get("excluded_education_pois") or [], "excluded", "高德API"),
        },
    }


def _api_total_count(result: dict) -> int:
    try:
        return int(result.get("api_total_count", result.get("count", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _poi_names(pois: list[dict], limit: int = 5) -> str:
    parts = []
    for poi in (pois or [])[:limit]:
        distance = poi.get("distance")
        suffix = f"{distance}m" if isinstance(distance, int) else "距离未知"
        parts.append(f"{poi.get('name')}({suffix})")
    return "、".join(parts)


def _amap_source(evidence_pois: list[dict], extra: Optional[dict] = None) -> dict:
    payload = {
        "data_source": "amap",
        "source_label": "高德地图 API 真实 POI" if evidence_pois else "高德地图 API（已查询，未返回可用 POI）",
        "is_simulated": False,
        "evidence_pois": (evidence_pois or [])[:10],
    }
    if extra:
        payload.update(extra)
    return payload


EDU_EXCLUDE_KEYWORDS = [
    "小学", "幼儿园", "早教", "培训", "补习", "辅导", "驾校", "舞蹈", "美术", "音乐",
    "普拉提", "瑜伽", "停车场", "停车", "校门", "东门", "西门", "南门", "北门",
    "食堂", "宿舍", "公寓", "快递", "医院", "附属", "家长", "招生", "维修",
]
HIGHER_EDU_KEYWORDS = [
    "大学", "学院", "高等专科学校", "职业技术学院", "职业学院", "高职", "大专",
    "技师学院", "开放大学", "成人高校",
]
SECONDARY_EDU_KEYWORDS = [
    "高中", "高级中学", "中学", "初中", "中专", "职高", "职业高中", "技工学校", "技校",
]


EDU_HARD_EXCLUDE_KEYWORDS = [
    "酒店", "宾馆", "民宿", "餐饮", "餐厅", "饭店", "小吃", "公交站", "地铁站", "停车场", "停车",
    "公寓", "宿舍", "图书馆", "校门", "东门", "西门", "南门", "北门", "食堂", "快递", "菜鸟",
    "培训", "早教", "托管", "辅导", "驾校", "舞蹈", "美术", "篮球", "维修", "汽车", "便利店",
    "超市", "商铺", "商城", "广场",
]
EDU_TYPE_EXCLUDE_KEYWORDS = [
    "交通设施", "公交车站", "停车场", "住宿服务", "餐饮服务", "购物服务", "生活服务", "商务住宅",
    "道路附属设施",
]
EDU_TYPECODE_INCLUDE_PREFIXES = ("1412",)
EDU_TYPECODE_EXCLUDE_PREFIXES = ("05", "06", "07", "10", "11", "12", "15", "16", "17", "18", "19", "20")


def _typecode(poi: dict) -> str:
    return str(poi.get("typecode") or "").strip()


def _typecode_startswith(poi: dict, prefixes: tuple[str, ...]) -> bool:
    code = _typecode(poi)
    return bool(code and any(code.startswith(prefix) for prefix in prefixes))


def _poi_text(poi: dict) -> str:
    return f"{poi.get('name') or ''} {poi.get('type') or ''} {poi.get('address') or ''} {_typecode(poi)}"


def _classify_education_poi(poi: dict) -> dict:
    name = str(poi.get("name") or "")
    poi_type = str(poi.get("type") or "")
    text = _poi_text(poi)
    enriched = dict(poi)

    for kw in EDU_HARD_EXCLUDE_KEYWORDS:
        if kw in text:
            enriched.update({
                "classification": "excluded_education",
                "classification_label": "排除项",
                "classification_reason": f"命中教育误匹配排除词：{kw}",
                "education_weight": 0.0,
            })
            return enriched

    for kw in EDU_TYPE_EXCLUDE_KEYWORDS:
        if kw in poi_type:
            enriched.update({
                "classification": "excluded_education",
                "classification_label": "排除项",
                "classification_reason": f"POI 类型不属于有效学校：{kw}",
                "education_weight": 0.0,
            })
            return enriched

    if _typecode_startswith(poi, EDU_TYPECODE_EXCLUDE_PREFIXES) and not _typecode_startswith(poi, EDU_TYPECODE_INCLUDE_PREFIXES):
        enriched.update({
            "classification": "excluded_education",
            "classification_label": "排除项",
            "classification_reason": f"高德 typecode={_typecode(poi)} 不属于学校教育大类",
            "education_weight": 0.0,
        })
        return enriched

    for kw in EDU_EXCLUDE_KEYWORDS:
        if kw in text:
            enriched.update({
                "classification": "excluded_education",
                "classification_label": "排除项",
                "classification_reason": f"命中排除词：{kw}",
                "education_weight": 0.0,
            })
            return enriched

    for kw in HIGHER_EDU_KEYWORDS:
        if kw in text:
            enriched.update({
                "classification": "higher_education",
                "classification_label": "高校/高职",
                "classification_reason": f"命中高校/高职词：{kw}",
                "education_weight": 1.0,
            })
            return enriched

    for kw in SECONDARY_EDU_KEYWORDS:
        if kw in text:
            enriched.update({
                "classification": "secondary_education",
                "classification_label": "初高中/中职",
                "classification_reason": f"命中初高中/中职词：{kw}",
                "education_weight": 0.35,
            })
            return enriched

    enriched.update({
        "classification": "education_candidate",
        "classification_label": "待核验学校",
        "classification_reason": "高德返回学校相关 POI，但未命中明确分类规则",
        "education_weight": 0.15,
    })
    return enriched


def _split_education_pois(pois: list[dict]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    classified = [_classify_education_poi(poi) for poi in pois or []]
    higher = [poi for poi in classified if poi.get("classification") == "higher_education"]
    secondary = [poi for poi in classified if poi.get("classification") == "secondary_education"]
    candidates = [poi for poi in classified if poi.get("classification") == "education_candidate"]
    excluded = [poi for poi in classified if poi.get("classification") == "excluded_education"]
    return higher, secondary, candidates, excluded


COMPETITOR_STRONG_KEYWORDS = [
    "网吧", "网咖", "电竞馆", "电竞俱乐部", "电子竞技", "电竞中心", "电竞社",
    "互联网上网服务"
]
COMPETITOR_WEAK_KEYWORDS = ["电竞酒店", "游戏厅", "游艺厅", "电玩城", "电子游艺"]
COMPETITOR_EXCLUDE_KEYWORDS = [
    "饮品", "奶茶", "茶饮", "咖啡", "餐饮", "小吃", "便利店", "超市", "停车场", "停车库", "培训",
    "传媒", "科技", "文化", "商贸", "服饰", "维修", "摄影", "棋牌", "台球", "桌游", "密室"
]
COMPETITOR_TYPE_INCLUDE_KEYWORDS = ["网吧", "网咖", "互联网上网服务"]
COMPETITOR_TYPE_CANDIDATE_KEYWORDS = ["电子游戏", "游艺", "娱乐场所", "休闲娱乐"]
COMPETITOR_TYPECODE_VALID_PREFIXES = ("0803",)
COMPETITOR_TYPECODE_EXCLUDE_PREFIXES = ("05", "06", "07", "10", "11", "12", "14", "15", "16", "17", "18", "19", "20")


def _classify_competitor_poi(poi: dict) -> dict:
    name = str(poi.get("name") or "")
    poi_type = str(poi.get("type") or "")
    text = _poi_text(poi)
    enriched = dict(poi)

    matched_exclude = next((kw for kw in COMPETITOR_EXCLUDE_KEYWORDS if kw in text), None)
    matched_strong = next((kw for kw in COMPETITOR_STRONG_KEYWORDS if kw in text), None)
    matched_weak = next((kw for kw in COMPETITOR_WEAK_KEYWORDS if kw in text), None)
    matched_type = next((kw for kw in COMPETITOR_TYPE_INCLUDE_KEYWORDS if kw in poi_type), None)
    matched_candidate_type = next((kw for kw in COMPETITOR_TYPE_CANDIDATE_KEYWORDS if kw in poi_type), None)

    if matched_exclude:
        enriched.update({
            "classification": "excluded_competitor",
            "classification_label": "已排除",
            "classification_reason": f"命中误匹配词：{matched_exclude}",
            "competitor_weight": 0.0,
        })
        return enriched

    if matched_strong or matched_type:
        enriched.update({
            "classification": "valid_competitor",
            "classification_label": "有效竞品",
            "classification_reason": f"命中明确竞品规则：{matched_strong or matched_type}；typecode={_typecode(poi) or '-'}",
            "competitor_weight": 1.0,
        })
        return enriched

    if matched_weak or matched_candidate_type or _typecode_startswith(poi, COMPETITOR_TYPECODE_VALID_PREFIXES):
        enriched.update({
            "classification": "competitor_candidate",
            "classification_label": "待核验竞品",
            "classification_reason": f"命中弱竞品/娱乐规则：{matched_weak or matched_candidate_type or _typecode(poi)}，需人工确认是否为电竞馆/网咖",
            "competitor_weight": 0.25,
        })
        return enriched

    if _typecode_startswith(poi, COMPETITOR_TYPECODE_EXCLUDE_PREFIXES):
        enriched.update({
            "classification": "excluded_competitor",
            "classification_label": "已排除",
            "classification_reason": f"高德 typecode={_typecode(poi)} 不属于电竞馆/网咖相关大类",
            "competitor_weight": 0.0,
        })
        return enriched

    enriched.update({
        "classification": "competitor_candidate",
        "classification_label": "待核验竞品",
        "classification_reason": "高德返回电竞/游戏相关 POI，但未命中明确竞品规则",
        "competitor_weight": 0.25,
    })
    return enriched


def _split_competitor_pois(pois: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    classified = [_classify_competitor_poi(poi) for poi in pois or []]
    valid = [poi for poi in classified if poi.get("classification") == "valid_competitor"]
    candidates = [poi for poi in classified if poi.get("classification") == "competitor_candidate"]
    excluded = [poi for poi in classified if poi.get("classification") == "excluded_competitor"]
    return valid, candidates, excluded


POLICY_REDLINE_KEYWORDS = [
    "小学", "幼儿园", "中学", "初中", "高中", "政府", "街道办", "派出所", "公安局", "法院", "检察院",
    "政务服务中心", "行政服务中心"
]


def _classify_policy_redline_poi(poi: dict) -> dict:
    name = str(poi.get("name") or "")
    poi_type = str(poi.get("type") or "")
    text = f"{name} {poi_type}"
    enriched = dict(poi)
    matched = next((kw for kw in POLICY_REDLINE_KEYWORDS if kw in text), None)
    enriched.update({
        "classification": "policy_redline",
        "classification_label": "政策红线",
        "classification_reason": f"200m 内命中政策红线词：{matched or '学校/政府机构'}",
    })
    return enriched


POLICY_HARD_INCLUDE_KEYWORDS_CN = [
    "小学", "幼儿园", "中学", "初中", "高中", "政府", "街道办", "派出所", "公安局", "法院", "检察院",
    "政务服务中心", "行政服务中心", "管委会",
]
POLICY_EXCLUDE_KEYWORDS_CN = [
    "公交站", "停车场", "停车", "维修", "汽车", "餐饮", "饭店", "酒店", "宾馆", "小区", "公寓",
    "商铺", "商场", "校门", "东门", "西门", "南门", "北门", "路口", "充电站", "地铁站",
]
POLICY_EXCLUDE_TYPES_CN = [
    "交通设施", "公交车站", "停车场", "汽车服务", "餐饮服务", "住宿服务", "购物服务", "商务住宅",
]
POLICY_TYPECODE_EXCLUDE_PREFIXES = ("05", "06", "07", "10", "11", "12", "15", "16", "17", "18", "19", "20")
POLICY_TYPECODE_INCLUDE_PREFIXES = ("1301", "1302", "1303", "1304", "1412")


def _classify_policy_redline_poi_strict(poi: dict) -> dict:
    name = str(poi.get("name") or "")
    poi_type = str(poi.get("type") or "")
    text = _poi_text(poi)
    enriched = dict(poi)
    excluded = next((kw for kw in POLICY_EXCLUDE_KEYWORDS_CN if kw in text), None)
    excluded_type = next((kw for kw in POLICY_EXCLUDE_TYPES_CN if kw in poi_type), None)
    matched = next((kw for kw in POLICY_HARD_INCLUDE_KEYWORDS_CN if kw in text), None)
    excluded_typecode = _typecode_startswith(poi, POLICY_TYPECODE_EXCLUDE_PREFIXES) and not _typecode_startswith(poi, POLICY_TYPECODE_INCLUDE_PREFIXES)
    if excluded or excluded_type or excluded_typecode:
        enriched.update({
            "classification": "excluded_policy_redline",
            "classification_label": "红线误匹配排除",
            "classification_reason": f"命中红线误匹配排除规则：{excluded or excluded_type or ('typecode=' + _typecode(poi))}",
        })
        return enriched
    typecode_hit = _typecode_startswith(poi, POLICY_TYPECODE_INCLUDE_PREFIXES)
    enriched.update({
        "classification": "policy_redline" if matched or typecode_hit else "policy_redline_candidate",
        "classification_label": "政策红线" if matched or typecode_hit else "待核验红线",
        "classification_reason": f"200m 内命中政策红线规则：{matched or ('typecode=' + _typecode(poi) if typecode_hit else '学校/政府机构相关 POI，需人工核验')}",
    })
    return enriched


async def score_policy_redline(longitude: float, latitude: float, api_key: str) -> dict:
    redline_result = await search_poi_around_pages(
        longitude,
        latitude,
        keywords="小学|幼儿园|中学|初中|高中|政府|街道办|派出所|公安局|法院|检察院|政务服务中心|行政服务中心",
        radius=200,
        api_key=api_key,
        max_pages=2,
    )
    raw_pois = redline_result.get("deduped_pois") or []
    classified_pois = [_classify_policy_redline_poi_strict(poi) for poi in raw_pois]
    redline_pois = [poi for poi in classified_pois if poi.get("classification") == "policy_redline"]
    candidate_pois = [poi for poi in classified_pois if poi.get("classification") == "policy_redline_candidate"]
    excluded_pois = [poi for poi in classified_pois if poi.get("classification") == "excluded_policy_redline"]
    return {
        "policy_redline_radius_m": 200,
        "policy_redline_count": len(redline_pois),
        "policy_redline_pois": redline_pois,
        "policy_redline_candidate_pois": candidate_pois,
        "excluded_policy_redline_pois": excluded_pois,
        "policy_redline_api_total_count": _api_total_count(redline_result),
        "policy_redline_raw_match_count": len(raw_pois),
        "policy_redline_candidate_count": len(candidate_pois),
        "excluded_policy_redline_count": len(excluded_pois),
        "policy_redline_summary": f"200m 内高德匹配政策红线 POI {len(raw_pois)} 条，计入真实红线 {len(redline_pois)} 条，待核验 {len(candidate_pois)} 条，排除误匹配 {len(excluded_pois)} 条；要求小学、幼儿园、中学、政府机构距离必须大于 200m",
        **_amap_source(redline_pois[:10]),
    }


ENTERTAINMENT_INCLUDE_KEYWORDS = [
    "KTV", "ktv", "酒吧", "台球", "密室", "剧本杀", "电影院", "影院", "棋牌", "游戏厅", "游艺厅", "电玩城",
]
ENTERTAINMENT_EXCLUDE_KEYWORDS = [
    "酒店", "宾馆", "餐饮", "饭店", "饮品", "奶茶", "咖啡", "便利店", "超市", "停车场", "培训", "学校",
    "维修", "汽车", "办公", "住宅", "公寓",
]
ENTERTAINMENT_TYPE_KEYWORDS = ["娱乐场所", "休闲娱乐", "体育休闲服务", "影剧院", "电影院", "KTV", "酒吧", "台球", "棋牌"]
ENTERTAINMENT_TYPECODE_PREFIXES = ("0803", "0805", "0806")
ENTERTAINMENT_TYPECODE_EXCLUDE_PREFIXES = ("05", "06", "07", "10", "11", "12", "14", "15", "16", "17", "18", "19", "20")


def _classify_entertainment_poi(poi: dict) -> dict:
    poi_type = str(poi.get("type") or "")
    text = _poi_text(poi)
    enriched = dict(poi)
    matched_exclude = next((kw for kw in ENTERTAINMENT_EXCLUDE_KEYWORDS if kw in text), None)
    if matched_exclude:
        enriched.update({
            "classification": "excluded_entertainment",
            "classification_label": "已排除",
            "classification_reason": f"命中娱乐误匹配排除词：{matched_exclude}",
        })
        return enriched

    matched_name = next((kw for kw in ENTERTAINMENT_INCLUDE_KEYWORDS if kw in text), None)
    matched_type = next((kw for kw in ENTERTAINMENT_TYPE_KEYWORDS if kw in poi_type), None)
    matched_typecode = _typecode_startswith(poi, ENTERTAINMENT_TYPECODE_PREFIXES)
    excluded_typecode = _typecode_startswith(poi, ENTERTAINMENT_TYPECODE_EXCLUDE_PREFIXES) and not matched_typecode
    if matched_name or matched_type or matched_typecode:
        enriched.update({
            "classification": "valid_entertainment",
            "classification_label": "有效娱乐配套",
            "classification_reason": f"命中娱乐配套规则：{matched_name or matched_type or ('typecode=' + _typecode(poi))}",
        })
        return enriched
    if excluded_typecode:
        enriched.update({
            "classification": "excluded_entertainment",
            "classification_label": "已排除",
            "classification_reason": f"高德 typecode={_typecode(poi)} 不属于娱乐配套大类",
        })
        return enriched
    enriched.update({
        "classification": "entertainment_candidate",
        "classification_label": "待核验娱乐配套",
        "classification_reason": "高德返回娱乐相关 POI，但未命中明确娱乐配套规则",
    })
    return enriched


def _split_entertainment_pois(pois: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    classified = [_classify_entertainment_poi(poi) for poi in pois or []]
    valid = [poi for poi in classified if poi.get("classification") == "valid_entertainment"]
    candidates = [poi for poi in classified if poi.get("classification") == "entertainment_candidate"]
    excluded = [poi for poi in classified if poi.get("classification") == "excluded_entertainment"]
    return valid, candidates, excluded


async def score_traffic(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    transit_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="地铁站|公交站|轻轨站",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )
    commercial_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="购物中心|商业广场|万达|万象城|吾悦广场",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )

    transit_pois = transit_result.get("deduped_pois") or []
    commercial_pois = commercial_result.get("deduped_pois") or []
    transit_count = len(transit_pois)
    commercial_count = len(commercial_pois)

    transit_score = min(100, transit_count * 15)
    commercial_score = min(100, commercial_count * 30)
    score = transit_score * 0.6 + commercial_score * 0.4

    detail = f"周边 {radius}m 内高德识别公交/地铁站 {transit_count} 个，商业综合体 {commercial_count} 个"
    if transit_pois:
        detail += f"；最近交通设施：{_poi_names(transit_pois, 4)}"
    if commercial_pois:
        detail += f"；主要商业设施：{_poi_names(commercial_pois, 4)}"

    return {
        "score": round(score, 1),
        "transit_count": transit_count,
        "commercial_count": commercial_count,
        "transit_api_total_count": _api_total_count(transit_result),
        "commercial_api_total_count": _api_total_count(commercial_result),
        "transit_pois": transit_pois,
        "commercial_pois": commercial_pois,
        "detail": detail,
        **_amap_source((transit_pois + commercial_pois)[:10]),
    }


async def score_competition(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    competitor_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="网吧|网咖|电竞|电竞馆|电竞酒店|电竞俱乐部|电子竞技|电竞中心|互联网上网服务|游戏厅|游艺厅",
        radius=radius,
        api_key=api_key,
        max_pages=3,
    )
    nearby_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="网吧|网咖|电竞|电竞馆|电竞酒店|电竞俱乐部|电子竞技|电竞中心|互联网上网服务|游戏厅|游艺厅",
        radius=500,
        api_key=api_key,
        max_pages=2,
    )

    raw_competitor_pois = competitor_result.get("deduped_pois") or []
    raw_nearby_pois = nearby_result.get("deduped_pois") or []
    valid_competitor_pois, competitor_candidate_pois, excluded_competitor_pois = _split_competitor_pois(raw_competitor_pois)
    nearby_valid_pois, nearby_candidate_pois, nearby_excluded_pois = _split_competitor_pois(raw_nearby_pois)
    competitor_pois = valid_competitor_pois + competitor_candidate_pois
    nearby_pois = nearby_valid_pois + nearby_candidate_pois
    competitor_count = len(valid_competitor_pois)
    competitor_candidate_count = len(competitor_candidate_pois)
    nearest_count_500m = len(nearby_valid_pois)

    if competitor_count == 0:
        competition_score = 100
    elif competitor_count <= 2:
        competition_score = 80
    elif competitor_count <= 5:
        competition_score = 60
    elif competitor_count <= 10:
        competition_score = 40
    else:
        competition_score = 20

    if nearest_count_500m > 0:
        competition_score = max(0, competition_score - nearest_count_500m * 15)

    detail = (
        f"周边 {radius}m 内高德原始匹配竞品相关 POI {len(raw_competitor_pois)} 条，"
        f"计入有效竞品 {competitor_count} 家，待核验 {competitor_candidate_count} 家，"
        f"排除误匹配 {len(excluded_competitor_pois)} 条；500m 内有效竞品 {nearest_count_500m} 家"
    )
    if competitor_pois:
        detail += f"；最近竞品：{_poi_names(competitor_pois, 5)}"

    return {
        "score": round(competition_score, 1),
        "competitor_count_1500m": competitor_count,
        "competitor_count_500m": nearest_count_500m,
        "competitor_api_total_count": _api_total_count(competitor_result),
        "competitor_raw_match_count": len(raw_competitor_pois),
        "competitor_effective_count": competitor_count,
        "competitor_candidate_count": competitor_candidate_count,
        "excluded_competitor_count": len(excluded_competitor_pois),
        "competitor_filter_summary": f"高德原始匹配 {len(raw_competitor_pois)} 条，计入有效竞品 {competitor_count} 家，待核验 {competitor_candidate_count} 家，排除 {len(excluded_competitor_pois)} 条误匹配",
        "competitor_pois_1500m": competitor_pois,
        "competitor_pois_500m": nearby_pois,
        "valid_competitor_pois": valid_competitor_pois,
        "competitor_candidate_pois": competitor_candidate_pois,
        "excluded_competitor_pois": excluded_competitor_pois,
        "excluded_competitor_pois_500m": nearby_excluded_pois,
        "amap_query_status": competitor_result.get("status"),
        "amap_query_info": competitor_result.get("info"),
        "amap_query_infocode": competitor_result.get("infocode"),
        "detail": detail,
        **_amap_source(competitor_pois[:10]),
    }


async def score_population(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    university_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="大学|学院|职业技术学院|高校|高中|中学|中专|职高|技校|技师学院|学校",
        radius=3000,
        api_key=api_key,
        max_pages=3,
    )
    residential_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="住宅小区|居民区|公寓",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )
    office_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="写字楼|办公楼|科技园|产业园",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )

    university_pois = university_result.get("deduped_pois") or []
    residential_pois = residential_result.get("deduped_pois") or []
    office_pois = office_result.get("deduped_pois") or []
    higher_education_pois, secondary_education_pois, education_candidate_pois, excluded_education_pois = _split_education_pois(university_pois)
    effective_education_pois = higher_education_pois + secondary_education_pois + education_candidate_pois
    core_education_pois, extended_education_pois = _split_rows_by_radius(effective_education_pois, radius)
    core_excluded_education_pois, extended_excluded_education_pois = _split_rows_by_radius(excluded_education_pois, radius)
    university_count = len(higher_education_pois)
    secondary_education_count = len(secondary_education_pois)
    education_candidate_count = len(education_candidate_pois)
    education_effective_count = len(effective_education_pois)
    excluded_education_count = len(excluded_education_pois)
    residential_count = len(residential_pois)
    office_count = len(office_pois)
    university_api_total = _api_total_count(university_result)

    education_weighted_count = (
        len(higher_education_pois) +
        len(secondary_education_pois) * 0.35 +
        len(education_candidate_pois) * 0.15
    )
    university_score = min(100, education_weighted_count * 35)
    residential_score = min(100, residential_count * 5)
    office_score = min(100, office_count * 10)
    score = university_score * 0.5 + residential_score * 0.3 + office_score * 0.2

    detail = (
        f"3km 内高德原始匹配教育 POI {university_api_total} 条，"
        f"计入有效教育客群 {education_effective_count} 条"
        f"（高校/高职 {university_count}，初高中/中职 {secondary_education_count}，待核验 {education_candidate_count}），"
        f"排除误匹配 {excluded_education_count} 条"
    )
    detail += f"，周边住宅 {residential_count} 个，写字楼/办公园区 {office_count} 个"
    if effective_education_pois:
        detail += f"；最近有效学校：{_poi_names(effective_education_pois, 6)}"

    return {
        "score": round(score, 1),
        "university_count": university_count,
        "university_api_total_count": university_api_total,
        "education_raw_match_count": university_api_total,
        "education_effective_count": education_effective_count,
        "higher_education_count": university_count,
        "secondary_education_count": secondary_education_count,
        "education_candidate_count": education_candidate_count,
        "excluded_education_count": excluded_education_count,
        "education_weighted_count": round(education_weighted_count, 2),
        "education_core_count": len(core_education_pois),
        "education_extended_count": len(extended_education_pois),
        "education_search_radius_m": 3000,
        "education_core_radius_m": radius,
        "education_filter_summary": f"高德原始匹配 {university_api_total} 条，计入有效教育客群 {education_effective_count} 条，排除 {excluded_education_count} 条误匹配",
        "residential_count": residential_count,
        "office_count": office_count,
        "university_pois": higher_education_pois,
        "education_pois": effective_education_pois,
        "education_core_pois": core_education_pois,
        "education_extended_pois": extended_education_pois,
        "higher_education_pois": higher_education_pois,
        "secondary_education_pois": secondary_education_pois,
        "education_candidate_pois": education_candidate_pois,
        "excluded_education_pois": excluded_education_pois,
        "excluded_education_core_pois": core_excluded_education_pois,
        "excluded_education_extended_pois": extended_excluded_education_pois,
        "residential_pois": residential_pois,
        "office_pois": office_pois,
        "detail": detail,
        **_amap_source((effective_education_pois + residential_pois + office_pois)[:10]),
    }


async def score_facility(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    food_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="餐厅|快餐|外卖|美食",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )
    convenience_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="便利店|超市|711|全家|罗森",
        radius=500,
        api_key=api_key,
        max_pages=2,
    )
    parking_result = await search_poi_around_pages(
        longitude, latitude,
        keywords="停车场|停车库",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )

    food_pois = food_result.get("deduped_pois") or []
    convenience_pois = convenience_result.get("deduped_pois") or []
    parking_pois = parking_result.get("deduped_pois") or []
    food_count = len(food_pois)
    convenience_count = len(convenience_pois)
    parking_count = len(parking_pois)

    score = (
        min(100, food_count * 3) * 0.4 +
        min(100, convenience_count * 20) * 0.3 +
        min(100, parking_count * 15) * 0.3
    )

    detail = f"周边高德识别餐饮 {food_count} 家，500m 内便利店/超市 {convenience_count} 家，停车场 {parking_count} 个"
    evidence = (food_pois + convenience_pois + parking_pois)[:10]
    if evidence:
        detail += f"；配套举例：{_poi_names(evidence, 6)}"

    return {
        "score": round(score, 1),
        "food_count": food_count,
        "convenience_count": convenience_count,
        "parking_count": parking_count,
        "food_pois": food_pois,
        "convenience_pois": convenience_pois,
        "parking_pois": parking_pois,
        "detail": detail,
        **_amap_source(evidence),
    }


async def score_facility(longitude: float, latitude: float, api_key: str, radius: int) -> dict:
    food_result = await search_poi_around_pages(
        longitude,
        latitude,
        keywords="餐厅|快餐|外卖|美食",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )
    convenience_result = await search_poi_around_pages(
        longitude,
        latitude,
        keywords="便利店|超市|711|全家|罗森",
        radius=500,
        api_key=api_key,
        max_pages=2,
    )
    parking_result = await search_poi_around_pages(
        longitude,
        latitude,
        keywords="停车场|停车库",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )
    entertainment_result = await search_poi_around_pages(
        longitude,
        latitude,
        keywords="KTV|酒吧|台球|密室|剧本杀|电影院|棋牌室|游戏厅|电玩城|娱乐",
        radius=radius,
        api_key=api_key,
        max_pages=2,
    )

    food_pois = food_result.get("deduped_pois") or []
    convenience_pois = convenience_result.get("deduped_pois") or []
    parking_pois = parking_result.get("deduped_pois") or []
    raw_entertainment_pois = entertainment_result.get("deduped_pois") or []
    entertainment_pois, entertainment_candidate_pois, excluded_entertainment_pois = _split_entertainment_pois(raw_entertainment_pois)
    food_count = len(food_pois)
    entertainment_count = len(entertainment_pois)
    convenience_count = len(convenience_pois)
    parking_count = len(parking_pois)

    score = (
        min(100, food_count * 3) * 0.3
        + min(100, entertainment_count * 12) * 0.25
        + min(100, convenience_count * 20) * 0.2
        + min(100, parking_count * 15) * 0.25
    )
    evidence = (food_pois + entertainment_pois + convenience_pois + parking_pois)[:10]
    detail = (
        f"周边高德识别餐饮 {food_count} 家，娱乐配套原始匹配 {len(raw_entertainment_pois)} 条，计入 {entertainment_count} 个，待核验 {len(entertainment_candidate_pois)} 个，排除 {len(excluded_entertainment_pois)} 个，"
        f"500m 内便利店/超市 {convenience_count} 家，停车场 {parking_count} 个"
    )
    if evidence:
        detail += f"；配套举例：{_poi_names(evidence, 6)}"

    return {
        "score": round(score, 1),
        "food_count": food_count,
        "entertainment_count": entertainment_count,
        "entertainment_raw_match_count": len(raw_entertainment_pois),
        "entertainment_candidate_count": len(entertainment_candidate_pois),
        "excluded_entertainment_count": len(excluded_entertainment_pois),
        "convenience_count": convenience_count,
        "parking_count": parking_count,
        "food_api_total_count": _api_total_count(food_result),
        "entertainment_api_total_count": _api_total_count(entertainment_result),
        "convenience_api_total_count": _api_total_count(convenience_result),
        "parking_api_total_count": _api_total_count(parking_result),
        "food_pois": food_pois,
        "entertainment_pois": entertainment_pois,
        "entertainment_candidate_pois": entertainment_candidate_pois,
        "excluded_entertainment_pois": excluded_entertainment_pois,
        "convenience_pois": convenience_pois,
        "parking_pois": parking_pois,
        "detail": detail,
        **_amap_source(evidence),
    }


def build_research_tables(dimension_results: Optional[dict], manual_data: Optional[dict]) -> dict:
    dimension_results = dimension_results or {}
    manual_data = manual_data or {}
    traffic = dimension_results.get("traffic") or {}
    competition = dimension_results.get("competition") or {}
    facility = dimension_results.get("facility") or {}
    population = dimension_results.get("population") or {}
    policy = dimension_results.get("policy") or {}

    included_manual_competitors = _research_status_rows(_included_rows(manual_data.get("competitors")), "manual_added", "人工调研")
    included_food = _research_status_rows(_included_rows(manual_data.get("food_places")), "manual_added", "人工调研")
    included_night_markets = _research_status_rows(_included_rows(manual_data.get("night_markets")), "manual_added", "人工调研")
    included_entertainment = _research_status_rows(_included_rows(manual_data.get("entertainment_places")), "manual_added", "人工调研")
    included_convenience = _research_status_rows(_included_rows(manual_data.get("convenience_stores")), "manual_added", "人工调研")
    included_parking = _research_status_rows(_included_rows(manual_data.get("parking_places")), "manual_added", "人工调研")

    education_core = population.get("education_core_pois") or []
    education_extended = population.get("education_extended_pois") or []
    education_pending = population.get("education_candidate_pois") or []
    education_all = education_core + education_extended

    return {
        "confirmed": {
            "traffic_stations": {
                "amap": _research_status_rows(traffic.get("transit_pois") or [], "included", "高德API"),
                "manual": _research_status_rows(_included_rows(manual_data.get("traffic_stations")), "manual_added", "人工调研"),
            },
            "commercial_places": {
                "amap": _research_status_rows(traffic.get("commercial_pois") or [], "included", "高德API"),
                "manual": _research_status_rows(_included_rows(manual_data.get("commercial_places")), "manual_added", "人工调研"),
            },
            "competitors": {
                "amap": _research_status_rows(competition.get("valid_competitor_pois") or [], "included", "高德API"),
                "pending": _research_status_rows(competition.get("competitor_candidate_pois") or [], "pending_review", "高德API"),
                "manual": included_manual_competitors,
            },
            "food_places": {
                "amap": _research_status_rows(facility.get("food_pois") or [], "included", "高德API"),
                "manual": included_food,
            },
            "night_markets": {
                "amap": [],
                "manual": included_night_markets,
            },
            "entertainment_places": {
                "amap": _research_status_rows(facility.get("entertainment_pois") or [], "included", "高德API"),
                "manual": included_entertainment,
            },
            "convenience_stores": {
                "amap": _research_status_rows(facility.get("convenience_pois") or [], "included", "高德API"),
                "manual": included_convenience,
            },
            "parking_places": {
                "amap": _research_status_rows(facility.get("parking_pois") or [], "included", "高德API"),
                "manual": included_parking,
            },
            "education": {
                "core": _research_status_rows(education_core, "included", "高德API"),
                "extended": _research_status_rows(education_extended, "included", "高德API"),
                "amap": _research_status_rows(education_all, "included", "高德API"),
                "pending": _research_status_rows(education_pending, "pending_review", "高德API"),
                "manual": _research_status_rows(_included_rows(manual_data.get("education_places")), "manual_added", "人工调研"),
            },
            "policy_redline": {
                "amap": _research_status_rows(policy.get("policy_redline_pois") or [], "included", "高德API"),
                "pending": _research_status_rows(policy.get("policy_redline_candidate_pois") or [], "pending_review", "高德API"),
                "manual": _research_status_rows(_included_rows(manual_data.get("policy_redline_review")), "manual_added", "人工调研"),
            },
            "residential_office": {
                "amap": _research_status_rows((population.get("residential_pois") or []) + (population.get("office_pois") or []), "included", "高德API"),
                "manual": _research_status_rows(_included_rows(manual_data.get("residential_office")), "manual_added", "人工调研"),
            },
        },
        "excluded": {
            "traffic_stations": _research_status_rows(_excluded_rows(manual_data.get("traffic_stations")), "excluded", "人工调研"),
            "commercial_places": _research_status_rows(_excluded_rows(manual_data.get("commercial_places")), "excluded", "人工调研"),
            "competitors": _research_status_rows(
                (competition.get("excluded_competitor_pois") or []) + _excluded_rows(manual_data.get("competitors")),
                "excluded",
                "高德API",
            ),
            "food_places": _research_status_rows(_excluded_rows(manual_data.get("food_places")), "excluded", "人工调研"),
            "night_markets": _research_status_rows(_excluded_rows(manual_data.get("night_markets")), "excluded", "人工调研"),
            "entertainment_places": _research_status_rows(_excluded_rows(manual_data.get("entertainment_places")), "excluded", "人工调研"),
            "convenience_stores": _research_status_rows(_excluded_rows(manual_data.get("convenience_stores")), "excluded", "人工调研"),
            "parking_places": _research_status_rows(_excluded_rows(manual_data.get("parking_places")), "excluded", "人工调研"),
            "education": _research_status_rows(
                (population.get("excluded_education_core_pois") or []) + (population.get("excluded_education_extended_pois") or []) + _excluded_rows(manual_data.get("education_places")),
                "excluded",
                "高德API",
            ),
            "policy_redline": _research_status_rows(
                (policy.get("excluded_policy_redline_pois") or []) + _excluded_rows(manual_data.get("policy_redline_review")),
                "excluded",
                "高德API",
            ),
            "residential_office": _research_status_rows(_excluded_rows(manual_data.get("residential_office")), "excluded", "人工调研"),
        },
    }


def build_poi_audit_summary(dimension_results: Optional[dict], research_tables: Optional[dict] = None) -> list[dict]:
    dimension_results = dimension_results or {}
    research_tables = research_tables or build_research_tables(dimension_results, {})
    confirmed = research_tables.get("confirmed") or {}
    excluded = research_tables.get("excluded") or {}
    traffic = dimension_results.get("traffic") or {}
    competition = dimension_results.get("competition") or {}
    facility = dimension_results.get("facility") or {}
    population = dimension_results.get("population") or {}
    policy = dimension_results.get("policy") or {}

    def count_table(key: str, parts=("amap", "manual")) -> tuple[int, int]:
        table = confirmed.get(key) or {}
        included = sum(len(table.get(part) or []) for part in parts)
        pending = len(table.get("pending") or [])
        return included, pending

    def excluded_count(key: str) -> int:
        return len(excluded.get(key) or [])

    competitor_included, competitor_pending = count_table("competitors")
    education_included = len((confirmed.get("education") or {}).get("core") or []) + len((confirmed.get("education") or {}).get("extended") or [])
    education_pending = len((confirmed.get("education") or {}).get("pending") or [])
    policy_included, policy_pending = count_table("policy_redline")
    traffic_included, traffic_pending = count_table("traffic_stations")
    commercial_included, commercial_pending = count_table("commercial_places")
    food_included, food_pending = count_table("food_places")
    entertainment_included, entertainment_pending = count_table("entertainment_places")
    convenience_included, convenience_pending = count_table("convenience_stores")
    parking_included, parking_pending = count_table("parking_places")
    residential_included, residential_pending = count_table("residential_office")

    return [
        _poi_audit_entry("traffic_stations", "交通站点", "地铁站|公交站|轻轨站", traffic.get("transit_api_total_count", 0), len(traffic.get("transit_pois") or []), traffic_included, traffic_pending, excluded_count("traffic_stations")),
        _poi_audit_entry("commercial_places", "商业设施", "购物中心|商业广场|万达|吾悦广场", traffic.get("commercial_api_total_count", 0), len(traffic.get("commercial_pois") or []), commercial_included, commercial_pending, excluded_count("commercial_places")),
        _poi_audit_entry(
            "competitors", "竞品", "网吧|网咖|电竞|游戏厅",
            competition.get("competitor_api_total_count", 0),
            competition.get("competitor_raw_match_count", 0),
            competitor_included, competitor_pending, excluded_count("competitors"),
            query_status=competition.get("amap_query_status"),
            query_info=competition.get("amap_query_info"),
            query_infocode=competition.get("amap_query_infocode"),
        ),
        _poi_audit_entry("food_places", "餐饮", "餐厅|快餐|外卖|美食", facility.get("food_api_total_count", facility.get("food_count", 0)), len(facility.get("food_pois") or []), food_included, food_pending, excluded_count("food_places")),
        _poi_audit_entry("entertainment_places", "娱乐配套", "KTV|酒吧|台球|密室|剧本杀|电影院|棋牌室|电玩城", facility.get("entertainment_api_total_count", facility.get("entertainment_count", 0)), facility.get("entertainment_raw_match_count", len(facility.get("entertainment_pois") or [])), entertainment_included, entertainment_pending, excluded_count("entertainment_places")),
        _poi_audit_entry("convenience_stores", "便利店", "便利店|超市|711|全家|罗森", facility.get("convenience_api_total_count", facility.get("convenience_count", 0)), len(facility.get("convenience_pois") or []), convenience_included, convenience_pending, excluded_count("convenience_stores")),
        _poi_audit_entry("parking_places", "停车场", "停车场|停车库", facility.get("parking_api_total_count", facility.get("parking_count", 0)), len(facility.get("parking_pois") or []), parking_included, parking_pending, excluded_count("parking_places")),
        _poi_audit_entry("education", "教育客群", "大学|学院|职业技术学院|高中|中学|中专|职高|技校", population.get("university_api_total_count", 0), len(population.get("education_pois") or []) + len(population.get("excluded_education_pois") or []), education_included, education_pending, excluded_count("education")),
        _poi_audit_entry("policy_redline", "政策红线", "小学|幼儿园|中学|政府|派出所", policy.get("policy_redline_api_total_count", 0), policy.get("policy_redline_raw_match_count", 0), policy_included, policy_pending, excluded_count("policy_redline")),
        _poi_audit_entry("residential_office", "住宅办公", "住宅小区|居民区|公寓|写字楼|办公楼", (population.get("residential_count") or 0) + (population.get("office_count") or 0), len((population.get("residential_pois") or []) + (population.get("office_pois") or [])), residential_included, residential_pending, excluded_count("residential_office")),
    ]


async def evaluate_location(
    address: str,
    city: Optional[str],
    db: Session,
    tenant_id: int,
    radius: int = DEFAULT_RADIUS,
    allow_mock_data: bool = False,
    manual_data: Optional[dict] = None,
    generate_report: bool = True,
    store_knowledge: bool = True,
    created_by: Optional[int] = None,
) -> AsyncGenerator[dict, None]:
    """
    完整单点评估（异步生成器，支持 SSE 流式输出）
    每个步骤 yield 一条日志，最终 yield 完整结果
    """
    log_steps = []

    def make_log(step_type: str, step_name: str, message: str, data: dict = None):
        entry = {
            "type": step_type,  # thinking / executing / result / warning / error
            "step": step_name,
            "message": message,
            "data": data or {}
        }
        log_steps.append(entry)
        return entry

    # Step 1: 意图分析
    manual_data = manual_data or {}
    yield make_log("thinking", "意图分析", f"收到选址评估请求，目标地址：{address}")
    await asyncio.sleep(0.1)

    # Step 2: 获取 API Key
    amap_key = get_amap_key(db)
    if not amap_key:
        yield make_log("error", "配置检查", "未配置高德 API Key，无法获取真实地理编码和周边 POI 数据。选址报告必须使用真实地图 API，请先配置高德 Key。")
        return
    yield make_log("executing", "配置检查", "高德 API Key 已就绪，开始获取真实地图 API 数据")

    await asyncio.sleep(0.1)

    # Step 3: 地理编码
    yield make_log("executing", "地理编码", f"调用高德 API 将地址转换为经纬度：{address}")
    longitude, latitude = None, None
    result = await geocode_address(address, city, amap_key)
    if result:
        longitude, latitude = result
        yield make_log("result", "地理编码", f"地理编码成功：经度 {longitude}，纬度 {latitude}",
                       {"longitude": longitude, "latitude": latitude, "data_source": "amap"})
    else:
        yield make_log("error", "地理编码", "高德地理编码失败，无法生成正式选址报告。请修正地址或检查高德 Web 服务 API Key。")
        return

    await asyncio.sleep(0.1)

    # Step 4: 获取评分权重
    yield make_log("executing", "权重加载", "从数据库加载当前评分权重（含历史数据动态调整）")
    active_model = get_active_model_version(db, tenant_id)
    weights = get_effective_weights(db, tenant_id)
    yield make_log("result", "权重加载", f"已加载 {len(weights)} 项评分权重",
                   {"weights_count": len(weights), "model_version_id": active_model.id if active_model else None, "model_version_name": active_model.name if active_model else "当前评分权重"})

    await asyncio.sleep(0.1)

    # Step 5-9: 各维度评分
    dimension_results = {}

    # 交通评分
    yield make_log("executing", "交通评分", f"搜索 {radius}m 内公交/地铁站和商业综合体...")
    traffic_data = await score_traffic(longitude, latitude, amap_key, radius)
    dimension_results["traffic"] = traffic_data
    yield make_log("result", "交通评分", f"交通评分：{traffic_data['score']} 分 | {traffic_data['detail']}", traffic_data)
    await asyncio.sleep(0.1)

    # 竞品评分
    yield make_log("executing", "竞品分析", f"搜索 {radius}m 内网吧/电竞馆竞品...")
    competition_data = await score_competition(longitude, latitude, amap_key, radius)
    dimension_results["competition"] = competition_data
    yield make_log("result", "竞品分析", f"竞品评分：{competition_data['score']} 分 | {competition_data['detail']}", competition_data)

    local_competitors = _load_local_competitors(db, tenant_id, longitude, latitude, radius)
    if local_competitors:
        yield make_log("result", "竞品档案", f"本地竞品档案命中 {len(local_competitors)} 家，将并入竞品强度和容量判断", {"local_competitors": local_competitors[:10]})

    # 竞品数量为0时，主动扩大搜索范围验证
    if competition_data["competitor_count_1500m"] == 0:
        yield make_log("thinking", "竞品分析", "1500m 内无竞品，扩大至 3000m 范围进行二次验证...")
        wider_count = await get_competitor_count(longitude, latitude, 3000, amap_key)
        yield make_log("result", "竞品分析", f"3000m 内竞品数量：{wider_count} 家",
                       {"competitor_count_3000m": wider_count, "data_source": "amap"})
        dimension_results["competition"]["competitor_count_3000m"] = wider_count
    await asyncio.sleep(0.1)

    # 客群评分
    yield make_log("executing", "客群分析", "搜索周边高校、住宅、写字楼...")
    population_data = await score_population(longitude, latitude, amap_key, radius)
    dimension_results["population"] = population_data
    yield make_log("result", "客群分析", f"客群评分：{population_data['score']} 分 | {population_data['detail']}", population_data)
    await asyncio.sleep(0.1)

    competition_data = _apply_competitor_research(competition_data, population_data, manual_data, local_competitors, allow_mock_data)
    dimension_results["competition"] = competition_data
    capacity = competition_data.get("market_capacity") or {}
    if capacity.get("can_calculate"):
        yield make_log("result", "商圈容量", capacity.get("detail", "商圈容量已计算"), capacity)
    else:
        yield make_log("warning", "商圈容量", capacity.get("detail", "缺少商圈容量参数，暂未计算"), capacity)
    await asyncio.sleep(0.1)

    # 配套设施评分
    yield make_log("executing", "配套设施", "搜索周边餐饮、便利店、停车场...")
    facility_data = await score_facility(longitude, latitude, amap_key, radius)
    facility_data = _apply_manual_facility_data(facility_data, manual_data)
    dimension_results["facility"] = facility_data
    yield make_log("result", "配套设施", f"配套评分：{facility_data['score']} 分 | {facility_data['detail']}", facility_data)
    await asyncio.sleep(0.1)

    # 租金维度（优先使用用户补充的真实数据）
    monthly_rent = _to_float(_nested_manual_value(manual_data, "property_conditions", "monthly_rent", "monthly_rent"))
    area_sqm = _to_float(_nested_manual_value(manual_data, "property_conditions", "area_sqm", "area_sqm"))
    if monthly_rent and area_sqm:
        rent_per_sqm = monthly_rent / area_sqm
        if rent_per_sqm <= 80:
            rent_score = 90.0
        elif rent_per_sqm <= 120:
            rent_score = 75.0
        elif rent_per_sqm <= 180:
            rent_score = 60.0
        elif rent_per_sqm <= 250:
            rent_score = 45.0
        else:
            rent_score = 30.0
        dimension_results["rent"] = {
            "score": rent_score,
            "detail": f"用户提供真实租金：月租 {monthly_rent:.0f} 元，面积 {area_sqm:.0f} ㎡，约 {rent_per_sqm:.1f} 元/㎡/月",
            "monthly_rent": monthly_rent,
            "area_sqm": area_sqm,
            "rent_per_sqm": round(rent_per_sqm, 1),
            "data_source": "user",
            "is_simulated": False,
        }
        dimension_results["rent"] = _apply_property_conditions(dimension_results["rent"], manual_data)
        yield make_log("result", "租金评分", f"已使用用户提供租金数据，租金评分 {rent_score} 分")
    elif allow_mock_data:
        dimension_results["rent"] = {"score": 60.0, "detail": "用户未提供租金，已授权使用中性模拟评分", "data_source": "simulation", "is_simulated": True}
        dimension_results["rent"] = _apply_property_conditions(dimension_results["rent"], manual_data)
        yield make_log("warning", "租金评分", "用户未提供租金，已按授权使用中性模拟评分 60 分")
    else:
        dimension_results["rent"] = {
            "score": 60.0,
            "detail": "缺少月租金和面积，初版报告按中性分占位；正式投资决策前必须在调研工作台补齐后重新生成报告",
            "data_source": "missing",
            "source_label": "缺失/待人工调研",
            "is_simulated": False,
            "missing_fields": ["月租金", "面积"],
        }
        dimension_results["rent"] = _apply_property_conditions(dimension_results["rent"], manual_data)
        yield make_log("warning", "租金评分", "缺少真实租金/面积，已标记为待调研并按中性分生成初版报告")

    # 政策维度：先查真实地图红线，再叠加用户补充的政策说明
    yield make_log("executing", "政策红线", "检查 200m 内小学、幼儿园、中学、政府机构等政策红线 POI...")
    policy_redline_data = await score_policy_redline(longitude, latitude, amap_key)
    redline_count = policy_redline_data.get("policy_redline_count", 0)
    if redline_count:
        yield make_log(
            "warning",
            "政策红线",
            f"200m 内发现 {redline_count} 个政策红线 POI，政策环境将按高风险处理",
            policy_redline_data,
        )
    else:
        yield make_log("result", "政策红线", "200m 内未发现小学、幼儿园、中学、政府机构等政策红线 POI", policy_redline_data)

    policy_risk = (manual_data.get("policy_risk") or "").strip()
    policy_notes = (manual_data.get("policy_notes") or "").strip()
    if policy_risk or policy_notes:
        policy_score_map = {"low": 85.0, "medium": 65.0, "high": 35.0}
        policy_label_map = {"low": "低风险", "medium": "中等风险", "high": "高风险"}
        policy_score = policy_score_map.get(policy_risk, 75.0)
        policy_label = policy_label_map.get(policy_risk, "未明确风险等级")
        detail = f"用户提供政策/合规信息：{policy_label}"
        if policy_notes:
            detail += f"，{policy_notes}"
        if redline_count:
            policy_score = min(policy_score, 25.0)
            detail += f"；政策红线：{policy_redline_data.get('policy_redline_summary')}"
        dimension_results["policy"] = {
            "score": policy_score,
            "detail": detail,
            "data_source": "amap_user",
            "source_label": "高德地图 API + 用户补充",
            "is_simulated": False,
            **policy_redline_data,
        }
        yield make_log("result", "政策评分", f"已使用用户提供政策信息，政策评分 {policy_score} 分")
    elif allow_mock_data:
        policy_score = 25.0 if redline_count else 75.0
        detail = "用户未提供政策信息，已授权使用中性模拟评分"
        if redline_count:
            detail = f"{policy_redline_data.get('policy_redline_summary')}；因命中政策红线，按高风险评分"
        dimension_results["policy"] = {
            "score": policy_score,
            "detail": detail,
            "data_source": "amap_simulation" if redline_count else "simulation",
            "source_label": "高德地图 API + 授权估算" if redline_count else "模拟数据",
            "is_simulated": not bool(redline_count),
            **policy_redline_data,
        }
        yield make_log("warning", "政策评分", f"用户未提供政策信息，政策评分 {policy_score} 分")
    else:
        if redline_count:
            dimension_results["policy"] = {
                "score": 25.0,
                "detail": f"{policy_redline_data.get('policy_redline_summary')}；缺少用户补充政策说明，已按政策红线高风险评分",
                "data_source": "amap",
                "source_label": "高德地图 API 真实 POI",
                "is_simulated": False,
                **policy_redline_data,
            }
            yield make_log("warning", "政策评分", "缺少用户政策说明，但已命中政策红线，按高风险继续生成报告")
        else:
            dimension_results["policy"] = {
                "score": 70.0,
                "detail": "200m 政策红线未命中，但缺少消防、证照、物业限制等人工政策说明；初版报告仅作筛选参考",
                "data_source": "amap_missing_user",
                "source_label": "高德地图 API + 缺失/待人工调研",
                "is_simulated": False,
                "missing_fields": ["消防/证照/物业限制说明", "政策风险等级"],
                **policy_redline_data,
            }
            yield make_log("warning", "政策评分", "缺少用户政策说明，已标记为待调研并继续生成初版报告")

    await asyncio.sleep(0.1)

    # Step 10: 综合评分计算
    yield make_log("executing", "综合评分", "根据各维度评分和权重计算综合得分...")

    dimension_weight_map = build_dimension_weight_map(weights)

    # 归一化权重
    total_weight = sum(dimension_weight_map.values())
    normalized_weights = {k: v / total_weight for k, v in dimension_weight_map.items()}

    total_score = sum(
        dimension_results.get(dim, {}).get("score", 60) * w
        for dim, w in normalized_weights.items()
    )
    total_score = round(total_score, 1)

    # 评级
    if total_score >= 80:
        grade = "A"
        grade_label = "强烈推荐"
        grade_color = "#67c23a"
    elif total_score >= 65:
        grade = "B"
        grade_label = "建议考虑"
        grade_color = "#409eff"
    elif total_score >= 50:
        grade = "C"
        grade_label = "谨慎评估"
        grade_color = "#e6a23c"
    else:
        grade = "D"
        grade_label = "不建议"
        grade_color = "#f56c6c"

    yield make_log("result", "综合评分", f"综合评分：{total_score} 分，评级：{grade}（{grade_label}）",
                   {"total_score": total_score, "grade": grade, "grade_label": grade_label})

    await asyncio.sleep(0.1)

    # 最终结果
    quality_issues = detect_data_quality_issues(address, dimension_results)
    data_quality = _build_data_quality(amap_key, dimension_results)
    data_quality["issues"] = quality_issues
    data_quality["has_issues"] = bool(quality_issues)
    research_status = build_research_required_fields(manual_data)
    research_tables = build_research_tables(dimension_results, manual_data)
    poi_audit_summary = build_poi_audit_summary(dimension_results, research_tables)
    factor_breakdown = build_factor_breakdown(dimension_results, weights, manual_data)
    data_quality["poi_audit_summary"] = poi_audit_summary

    final_result = {
        "type": "final",
        "address": address,
        "longitude": longitude,
        "latitude": latitude,
        "total_score": total_score,
        "grade": grade,
        "grade_label": grade_label,
        "grade_color": grade_color,
        "dimensions": {
            dim: {
                "score": dimension_results.get(dim, {}).get("score", 0),
                "weight": round(normalized_weights.get(dim, 0) * 100, 1),
                "detail": dimension_results.get(dim, {}).get("detail", ""),
                "factor_breakdown": factor_breakdown.get(dim, []),
                **{k: v for k, v in dimension_results.get(dim, {}).items() if k not in ("score", "detail")}
            }
            for dim in ["traffic", "competition", "population", "rent", "facility", "policy"]
        },
        "log_steps": log_steps,
        "has_amap_key": bool(amap_key),
        "allow_mock_data": allow_mock_data,
        "manual_data": manual_data,
        "research_required_fields": research_status["items"],
        "research_completion_rate": research_status["completion_rate"],
        "confirmed_poi_tables": research_tables["confirmed"],
        "excluded_poi_tables": research_tables["excluded"],
        "poi_audit_summary": poi_audit_summary,
        "model_version": {
            "id": active_model.id if active_model else None,
            "name": active_model.name if active_model else "当前评分权重",
        },
        "data_quality": data_quality,
    }
    if quality_issues:
        yield make_log("warning", "数据质量校验", f"发现 {len(quality_issues)} 个疑似异常数据点，报告中将提示人工核验。", {"issues": quality_issues})

    rag_evidence = []
    try:
        from app.services.vector_rag import hybrid_search
        query_parts = [f"电竞馆选址评估 {address}", grade_label]
        for dim_data in dimension_results.values():
            if dim_data.get("detail"):
                query_parts.append(str(dim_data["detail"]))
        candidates = await hybrid_search(
            query=" ".join(query_parts),
            tenant_id=tenant_id,
            db=db,
            source_types=["document_experience", "store_experience", "evaluation_result"],
            top_k=4,
        )
        for item in candidates:
            meta = item.get("metadata", {}) or {}
            rag_evidence.append({
                "source_type": item.get("source_type"),
                "source_name": meta.get("filename") or meta.get("store_name") or meta.get("address") or "历史知识",
                "scope_type": meta.get("scope_type"),
                "content": item.get("content", "")[:260],
                "similarity": round(item.get("fusion_score", 0) * 100, 1),
            })
        if rag_evidence:
            yield make_log("result", "历史经验检索", f"已检索到 {len(rag_evidence)} 条历史经验/调研文档依据")
        else:
            yield make_log("warning", "历史经验检索", "未检索到可引用的历史经验或调研文档")
    except Exception as e:
        logger.warning(f"历史经验检索失败，不影响评分结果: {e}")
        yield make_log("warning", "历史经验检索", "知识库暂不可用，报告将仅基于本次评分数据生成")
    final_result["rag_evidence"] = rag_evidence

    # Step 11: LLM 生成完整选址报告
    if generate_report:
        yield make_log("executing", "AI报告生成", "调用大模型生成完整选址分析报告...")
        try:
            from app.services.llm_gateway import chat_completion_stream as llm_stream
            model_name = active_model.name if active_model else "当前评分权重"
            report_prompt = _build_report_prompt(address, total_score, grade, grade_label, dimension_results, normalized_weights, rag_evidence, model_name)
            report_messages = [{"role": "user", "content": report_prompt}]
            report_system = """你是一位专业的电竞馆选址分析师。请基于提供的评分数据，生成一份结构清晰、内容全面的选址分析报告。
报告要求：
- 使用 Markdown 格式，包含标题、加粗、列表、表格
- 包含：综合结论、各维度深度分析、核心风险点、具体建议
- 语言专业、数据具体，避免模糊表述
- 报告长度应在 800-1200 字之间
"""
            llm_report_content = ""
            async for token in llm_stream(report_messages, db, system_prompt=report_system):
                llm_report_content += token
                yield {"type": "llm", "data": {"content": token}}
            final_result["llm_report"] = llm_report_content
            yield make_log("result", "AI报告生成", f"AI 报告已生成，共 {len(llm_report_content)} 字")
        except Exception as e:
            logger.error(f"LLM 报告生成失败: {e}")
            yield make_log("warning", "AI报告生成", f"AI 报告生成失败，请检查大模型配置: {str(e)[:100]}")
    else:
        final_result["llm_report"] = ""
        yield make_log("result", "AI报告生成", "对比评估已跳过单地址长报告生成，进入综合对比阶段")

    # Step 12: 将评估结果写入知识库（学习闭环）
    evaluation_id = persist_evaluation_record(
        db=db,
        tenant_id=tenant_id,
        created_by=created_by,
        radius=radius,
        final_result=final_result,
        normalized_weights=normalized_weights,
        llm_report=final_result.get("llm_report", ""),
        rag_evidence=rag_evidence,
        model_version=active_model,
        quality_issues=quality_issues,
    )
    final_result["evaluation_id"] = evaluation_id
    if evaluation_id:
        yield make_log("result", "评估记录", f"评估结果已保存（ID: {evaluation_id}），可用于反馈和持续学习。")

    if store_knowledge:
        yield make_log("executing", "知识库写入", "将本次评估结果写入知识库，用于未来相似地址参考...")
        try:
            vec_id = await store_evaluation_to_knowledge(
                address=address,
                longitude=longitude,
                latitude=latitude,
                total_score=total_score,
                grade=grade,
                grade_label=grade_label,
                dimension_results=dimension_results,
                normalized_weights=normalized_weights,
                llm_report=final_result.get("llm_report", ""),
                tenant_id=tenant_id,
                db=db,
                source_id=evaluation_id,
            )
            if vec_id:
                yield make_log("result", "知识库写入", f"评估案例已写入知识库（ID: {vec_id}），系统将越用越聪明")
            else:
                yield make_log("warning", "知识库写入", "知识库写入跳过（未配置嵌入模型或 pgvector 未启用）")
        except Exception as e:
            logger.warning(f"知识库写入失败（不影响评估结果）: {e}")
            yield make_log("warning", "知识库写入", "知识库写入失败，不影响本次评估结果")
    else:
        yield make_log("result", "知识库写入", "对比评估已跳过单地址知识库写入，避免重复写入和等待")

    yield final_result


async def store_evaluation_to_knowledge(
    address: str,
    longitude: float,
    latitude: float,
    total_score: float,
    grade: str,
    grade_label: str,
    dimension_results: dict,
    normalized_weights: dict,
    llm_report: str,
    tenant_id: int,
    db: Session,
    source_id: Optional[int] = None,
) -> Optional[int]:
    """
    将单次评估结果向量化存入知识库
    格式化为自然语言，便于后续语义检索
    """
    try:
        from app.services.vector_rag import store_text_as_vector

        dim_names = {
            "traffic": "交通与人流",
            "competition": "竞品分析",
            "population": "目标客群",
            "rent": "租金与成本",
            "facility": "配套设施",
            "policy": "政策环境",
        }

        dim_lines = []
        for dim, name in dim_names.items():
            data = dimension_results.get(dim, {})
            score = data.get("score", 0)
            detail = data.get("detail", "")
            weight_pct = round(normalized_weights.get(dim, 0) * 100, 1)
            dim_lines.append(f"{name}：{score}分（权重{weight_pct}%），{detail}")

        # 构建自然语言描述，便于语义检索
        content = f"""【选址评估案例】
地址：{address}
坐标：经度{longitude:.4f} 纬度{latitude:.4f}
综合评分：{total_score}分，评级：{grade}级（{grade_label}）

各维度评分：
{chr(10).join(dim_lines)}
"""
        if llm_report:
            # 只取报告前 500 字，避免向量内容过长
            content += f"\nAI分析摘要：{llm_report[:500]}..."

        metadata = {
            "type": "evaluation_result",
            "address": address,
            "longitude": longitude,
            "latitude": latitude,
            "total_score": total_score,
            "grade": grade,
                "grade_label": grade_label,
                "evaluation_id": source_id,
                "dimensions": {
                dim: dimension_results.get(dim, {}).get("score", 0)
                for dim in dim_names
            },
        }

        # 用坐标生成唯一 source_id（避免重复存储同一地址）
        import hashlib
        # 对 md5 hash 取模确保在 PostgreSQL int32 范围内（最大 2^31-1）
        if source_id is None:
            source_id = int(hashlib.md5(f"{tenant_id}:{address}".encode()).hexdigest()[:8], 16) % (2**31 - 1)

        return await store_text_as_vector(
            content=content,
            metadata=metadata,
            source_type="evaluation_result",
            source_id=source_id,
            tenant_id=tenant_id,
            db=db,
        )
    except Exception as e:
        logger.warning(f"评估结果知识库写入失败: {e}")
        return None


def _build_report_prompt(
    address: str,
    total_score: float,
    grade: str,
    grade_label: str,
    dimension_results: dict,
    normalized_weights: dict,
    rag_evidence: Optional[list[dict]] = None,
    model_version_name: str = "当前评分权重",
) -> str:
    """构建 LLM 报告生成的 prompt"""
    dim_names = {
        "traffic": "交通与人流",
        "competition": "竞品分析",
        "population": "目标客群",
        "rent": "租金与成本",
        "facility": "配套设施",
        "policy": "政策环境",
    }
    dim_lines = []
    for dim, name in dim_names.items():
        data = dimension_results.get(dim, {})
        score = data.get("score", 0)
        detail = data.get("detail", "")
        source_label = data.get("source_label") or (
            "模拟/估算数据" if data.get("is_simulated") else
            ("用户提供数据" if data.get("data_source") == "user" else "外部真实数据")
        )
        pois = data.get("evidence_pois") or []
        if pois:
            detail = f"{detail}；地图证据：{_poi_names(pois, 6)}"
        if dim == "population":
            education_summary = data.get("education_filter_summary")
            if education_summary:
                detail = f"{detail}；教育 POI 清洗：{education_summary}"
            excluded = data.get("excluded_education_pois") or []
            if excluded:
                detail = f"{detail}；已排除误匹配示例：{_poi_names(excluded, 5)}"
        if dim == "competition":
            capacity = data.get("market_capacity") or {}
            if capacity.get("can_calculate"):
                detail = f"{detail}；商圈容量：{capacity.get('detail')}"
            elif capacity.get("missing_fields"):
                detail = f"{detail}；商圈容量缺失字段：{', '.join(capacity.get('missing_fields') or [])}"
            confirmed = (data.get("local_competitor_profiles") or []) + (data.get("manual_competitors") or [])
            if confirmed:
                detail = f"{detail}；人工/本地确认竞品：{_poi_names(confirmed, 6)}"
        if dim == "facility" and data.get("manual_facility_data"):
            detail = f"{detail}；配套人工补充：{json.dumps(data.get('manual_facility_data'), ensure_ascii=False)}"
        if dim == "rent" and data.get("property_conditions"):
            detail = f"{detail}；物业人工补充：{json.dumps(data.get('property_conditions'), ensure_ascii=False)}"
        if data.get("is_simulated"):
            detail = f"{detail}；注意：该维度未使用真实外部数据，属于模拟/估算"
        weight_pct = round(normalized_weights.get(dim, 0) * 100, 1)
        dim_lines.append(f"- **{name}**：{score}分（权重 {weight_pct}%），数据来源：{source_label}；{detail}")

    evidence_lines = []
    for item in (rag_evidence or [])[:4]:
        source_name = item.get("source_name") or "历史知识"
        source_type = item.get("source_type") or "unknown"
        similarity = item.get("similarity", 0)
        content = item.get("content", "")
        evidence_lines.append(f"- **{source_name}**（{source_type}，相关度 {similarity}%）：{content}")
    evidence_section = "\n".join(evidence_lines) if evidence_lines else "暂无可引用的历史经验或调研文档。"

    return f"""请对以下电竞馆选址评估结果生成完整分析报告：

## 基本信息
- **评估地址**：{address}
- **综合评分**：{total_score} 分
- **综合评级**：{grade}级（{grade_label}）
- **本次使用模型版本**：{model_version_name}

## 各维度评分明细
{chr(10).join(dim_lines)}

## 历史经验/调研文档依据
{evidence_section}

请生成包含以下内容的完整选址分析报告：
1. **综合结论**：给出明确的开店建议和理由
2. **本次使用模型版本**：说明本报告使用的评分模型和主要权重依据
3. **外部真实数据依据**：列出高德 POI、用户补充数据、数据质量提示
4. **历史规律依据**：引用历史经验、调研文档或相似案例
5. **各维度评分和权重**：解释每个维度的分数、权重、优势和不足
6. **风险项**：列出 2-3 个最需关注的风险因素
7. **可执行建议**：提出 3 条可执行的选址优化建议
8. **反馈入口提示**：提醒用户评估后提交准确/不准确和实际经营结果，用于下一版模型优化

数据使用要求：
- 只能引用上方已提供的真实 POI、用户补充数据、历史经验，不得编造地图信息或距离。
- 对“模拟/估算数据”“用户未提供真实数据”的维度，必须在报告中明确标注。
- 高德地图原始匹配数与去重后的 POI 数不一致时，以去重后的 POI 作为结论依据，并提示可能存在 POI 过匹配。
"""
