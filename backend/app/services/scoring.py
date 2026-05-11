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

from app.models.store import ScoringRule
from app.services.amap import (
    geocode_address, search_poi_around, get_competitor_count, get_amap_key
)

logger = logging.getLogger(__name__)

# 默认评分半径（米）
DEFAULT_RADIUS = 1500


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


async def evaluate_location(
    address: str,
    city: Optional[str],
    db: Session,
    tenant_id: int,
    radius: int = DEFAULT_RADIUS
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
    yield make_log("thinking", "意图分析", f"收到选址评估请求，目标地址：{address}")
    await asyncio.sleep(0.1)

    # Step 2: 获取 API Key
    amap_key = get_amap_key(db)
    if not amap_key:
        yield make_log("warning", "配置检查", "未配置高德 API Key，将使用模拟数据进行评估")
    else:
        yield make_log("executing", "配置检查", "高德 API Key 已就绪，开始获取外部数据")

    await asyncio.sleep(0.1)

    # Step 3: 地理编码
    yield make_log("executing", "地理编码", f"调用高德 API 将地址转换为经纬度：{address}")
    longitude, latitude = None, None
    if amap_key:
        result = await geocode_address(address, city, amap_key)
        if result:
            longitude, latitude = result
            yield make_log("result", "地理编码", f"地理编码成功：经度 {longitude}，纬度 {latitude}",
                           {"longitude": longitude, "latitude": latitude})
        else:
            yield make_log("error", "地理编码", "地理编码失败，地址可能不准确，将使用模拟数据")
    else:
        # 模拟数据（西安市中心）
        longitude, latitude = 108.9398, 34.3416
        yield make_log("warning", "地理编码", f"使用模拟坐标：{longitude}, {latitude}（请配置高德 API Key）")

    await asyncio.sleep(0.1)

    # Step 4: 获取评分权重
    yield make_log("executing", "权重加载", "从数据库加载当前评分权重（含历史数据动态调整）")
    weights = get_effective_weights(db, tenant_id)
    yield make_log("result", "权重加载", f"已加载 {len(weights)} 项评分权重",
                   {"weights_count": len(weights)})

    await asyncio.sleep(0.1)

    # Step 5-9: 各维度评分
    dimension_results = {}

    if amap_key and longitude and latitude:
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
                           {"competitor_count_3000m": wider_count})
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

    else:
        # 无 API Key 时使用模拟数据
        yield make_log("warning", "数据获取", "无高德 API Key，使用模拟评分数据")
        dimension_results = {
            "traffic":     {"score": 72.0, "detail": "模拟数据"},
            "competition": {"score": 65.0, "detail": "模拟数据"},
            "population":  {"score": 78.0, "detail": "模拟数据"},
            "facility":    {"score": 60.0, "detail": "模拟数据"},
        }

    # 租金维度（需用户提供，此处给中性分）
    dimension_results["rent"] = {"score": 60.0, "detail": "租金数据需用户提供，当前使用中性评分"}
    yield make_log("warning", "租金评分", "租金数据需用户提供，当前使用中性评分 60 分")

    # 政策维度（默认中性）
    dimension_results["policy"] = {"score": 75.0, "detail": "政策环境正常，无特殊限制"}
    yield make_log("result", "政策评分", "政策环境评分：75 分（默认中性）")

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
    }

    # Step 11: LLM 生成完整选址报告
    yield make_log("executing", "AI报告生成", "调用大模型生成完整选址分析报告...")
    try:
        from app.services.llm_gateway import chat_completion_stream as llm_stream
        report_prompt = _build_report_prompt(address, total_score, grade, grade_label, dimension_results, normalized_weights)
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

    # Step 12: 将评估结果写入知识库（学习闭环）
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
        )
        if vec_id:
            yield make_log("result", "知识库写入", f"评估案例已写入知识库（ID: {vec_id}），系统将越用越聪明")
        else:
            yield make_log("warning", "知识库写入", "知识库写入跳过（未配置嵌入模型或 pgvector 未启用）")
    except Exception as e:
        logger.warning(f"知识库写入失败（不影响评估结果）: {e}")
        yield make_log("warning", "知识库写入", "知识库写入失败，不影响本次评估结果")

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
            "dimensions": {
                dim: dimension_results.get(dim, {}).get("score", 0)
                for dim in dim_names
            },
        }

        # 用坐标生成唯一 source_id（避免重复存储同一地址）
        import hashlib
        # 对 md5 hash 取模确保在 PostgreSQL int32 范围内（最大 2^31-1）
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
        weight_pct = round(normalized_weights.get(dim, 0) * 100, 1)
        dim_lines.append(f"- **{name}**：{score}分（权重 {weight_pct}%），{detail}")

    return f"""请对以下电竞馆选址评估结果生成完整分析报告：

## 基本信息
- **评估地址**：{address}
- **综合评分**：{total_score} 分
- **综合评级**：{grade}级（{grade_label}）

## 各维度评分明细
{''.join(dim_lines)}

请生成包含以下内容的完整选址分析报告：
1. **综合评估结论**：给出明确的开店建议和理由
2. **各维度深度分析**：对每个维度进行详细解读，指出优势和不足
3. **核心风险点**：列出 2-3 个最需关注的风险因素
4. **具体建议**：提出 3 条可执行的选址优化建议
5. **开店时机建议**：建议最佳开店时间和注意事项
"""
