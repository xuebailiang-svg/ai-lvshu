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
from typing import Optional, AsyncGenerator
from sqlalchemy.orm import Session

from app.models.store import DataQualityIssue, EvaluationRecord, ScoringModelVersion, ScoringRule
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
    active_model = get_active_model_version(db, tenant_id)
    if active_model and active_model.weight_snapshot:
        weights = {}
        for key, item in active_model.weight_snapshot.items():
            if isinstance(item, dict):
                weights[key] = item.get("effective_weight", item.get("dynamic_weight", item.get("base_weight")))
            else:
                weights[key] = item
        return {k: v for k, v in weights.items() if v is not None}

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


def detect_data_quality_issues(address: str, dimension_results: dict) -> list[dict]:
    issues = []
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
        items.append({
            "key": key,
            "name": name,
            "status": "simulation" if source == "simulation" else "real",
            "source": source_label,
            "detail": data.get("detail", ""),
        })
    return {
        "has_simulation": any(item["status"] == "simulation" for item in items),
        "items": items,
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


def _classify_education_poi(poi: dict) -> dict:
    name = str(poi.get("name") or "")
    poi_type = str(poi.get("type") or "")
    text = f"{name} {poi_type}"
    enriched = dict(poi)

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
    "网吧", "网咖", "电竞馆", "电竞酒店", "电竞俱乐部", "电子竞技", "电竞中心", "电竞社",
    "游戏厅", "游艺厅", "互联网上网服务"
]
COMPETITOR_EXCLUDE_KEYWORDS = [
    "饮品", "奶茶", "茶饮", "咖啡", "餐饮", "小吃", "便利店", "超市", "停车场", "停车库", "培训",
    "传媒", "科技", "文化", "商贸", "服饰", "维修", "摄影", "棋牌", "台球", "桌游", "密室"
]


def _classify_competitor_poi(poi: dict) -> dict:
    name = str(poi.get("name") or "")
    poi_type = str(poi.get("type") or "")
    text = f"{name} {poi_type}"
    enriched = dict(poi)

    matched_exclude = next((kw for kw in COMPETITOR_EXCLUDE_KEYWORDS if kw in text), None)
    matched_strong = next((kw for kw in COMPETITOR_STRONG_KEYWORDS if kw in text), None)

    if matched_exclude:
        enriched.update({
            "classification": "excluded_competitor",
            "classification_label": "已排除",
            "classification_reason": f"命中误匹配词：{matched_exclude}",
            "competitor_weight": 0.0,
        })
        return enriched

    if matched_strong:
        enriched.update({
            "classification": "valid_competitor",
            "classification_label": "有效竞品",
            "classification_reason": f"命中明确竞品词：{matched_strong}",
            "competitor_weight": 1.0,
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
        "transit_pois": transit_pois[:10],
        "commercial_pois": commercial_pois[:10],
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
        "competitor_pois_1500m": competitor_pois[:50],
        "competitor_pois_500m": nearby_pois[:30],
        "valid_competitor_pois": valid_competitor_pois[:50],
        "competitor_candidate_pois": competitor_candidate_pois[:50],
        "excluded_competitor_pois": excluded_competitor_pois[:50],
        "excluded_competitor_pois_500m": nearby_excluded_pois[:30],
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
        "education_filter_summary": f"高德原始匹配 {university_api_total} 条，计入有效教育客群 {education_effective_count} 条，排除 {excluded_education_count} 条误匹配",
        "residential_count": residential_count,
        "office_count": office_count,
        "university_pois": higher_education_pois[:20],
        "education_pois": effective_education_pois[:30],
        "higher_education_pois": higher_education_pois[:20],
        "secondary_education_pois": secondary_education_pois[:20],
        "education_candidate_pois": education_candidate_pois[:20],
        "excluded_education_pois": excluded_education_pois[:30],
        "residential_pois": residential_pois[:10],
        "office_pois": office_pois[:10],
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
        "food_pois": food_pois[:10],
        "convenience_pois": convenience_pois[:10],
        "parking_pois": parking_pois[:10],
        "detail": detail,
        **_amap_source(evidence),
    }


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

    # 配套设施评分
    yield make_log("executing", "配套设施", "搜索周边餐饮、便利店、停车场...")
    facility_data = await score_facility(longitude, latitude, amap_key, radius)
    dimension_results["facility"] = facility_data
    yield make_log("result", "配套设施", f"配套评分：{facility_data['score']} 分 | {facility_data['detail']}", facility_data)
    await asyncio.sleep(0.1)

    # 租金维度（优先使用用户补充的真实数据）
    monthly_rent = _to_float(manual_data.get("monthly_rent"))
    area_sqm = _to_float(manual_data.get("area_sqm"))
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
        yield make_log("result", "租金评分", f"已使用用户提供租金数据，租金评分 {rent_score} 分")
    elif allow_mock_data:
        dimension_results["rent"] = {"score": 60.0, "detail": "用户未提供租金，已授权使用中性模拟评分", "data_source": "simulation", "is_simulated": True}
        yield make_log("warning", "租金评分", "用户未提供租金，已按授权使用中性模拟评分 60 分")
    else:
        yield make_log("error", "租金评分", "缺少真实租金数据。请补充月租金和面积，或明确点击“使用模拟数据”。")
        return

    # 政策维度（优先使用用户补充的真实说明）
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
        dimension_results["policy"] = {"score": policy_score, "detail": detail, "data_source": "user", "is_simulated": False}
        yield make_log("result", "政策评分", f"已使用用户提供政策信息，政策评分 {policy_score} 分")
    elif allow_mock_data:
        dimension_results["policy"] = {"score": 75.0, "detail": "用户未提供政策信息，已授权使用中性模拟评分", "data_source": "simulation", "is_simulated": True}
        yield make_log("warning", "政策评分", "用户未提供政策信息，已按授权使用中性模拟评分 75 分")
    else:
        yield make_log("error", "政策评分", "缺少政策/消防/证照限制说明。请补充政策风险，或明确点击“使用模拟数据”。")
        return

    await asyncio.sleep(0.1)

    # Step 10: 综合评分计算
    yield make_log("executing", "综合评分", "根据各维度评分和权重计算综合得分...")

    dimension_weight_map = {
        "traffic":     weights.get("traffic.foot_traffic", 0.25) + weights.get("traffic.transit_accessibility", 0.10),
        "competition": weights.get("competition.competitor_count", 0.20) + weights.get("competition.competitor_distance", 0.05),
        "population":  weights.get("population.young_density", 0.20) + weights.get("population.university_nearby", 0.05),
        "rent":        weights.get("rent.rent_ratio", 0.10),
        "facility":    weights.get("facility.commercial_density", 0.03),
        "policy":      weights.get("policy.policy_risk", 0.02),
    }

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
                **{k: v for k, v in dimension_results.get(dim, {}).items() if k not in ("score", "detail")}
            }
            for dim in ["traffic", "competition", "population", "rent", "facility", "policy"]
        },
        "log_steps": log_steps,
        "has_amap_key": bool(amap_key),
        "allow_mock_data": allow_mock_data,
        "manual_data": manual_data,
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
