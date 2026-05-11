"""
数据分析引擎
- 分析历史运营数据（营收、会员画像等）
- 提取成功模式（哪些因素与盈利相关）
- 调用大模型生成分析总结
- 自动更新评分权重（自适应评分闭环）
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.store import Store, RevenueRecord, MemberProfile, ScoringRule, UploadRecord

logger = logging.getLogger(__name__)


def analyze_member_profile_impact(db: Session, tenant_id: int) -> dict:
    """
    分析会员画像对营收的影响
    返回各年龄段的营收贡献占比，识别核心客群
    """
    profiles = db.query(MemberProfile).filter(
        MemberProfile.tenant_id == tenant_id
    ).all()

    if not profiles:
        return {}

    total_rev = {
        "age_under_18": 0, "age_18_22": 0, "age_23_25": 0,
        "age_26_30": 0, "age_31_35": 0, "age_over_35": 0
    }
    count = len(profiles)

    for p in profiles:
        total_rev["age_under_18"] += p.revenue_age_under_18 or 0
        total_rev["age_18_22"] += p.revenue_age_18_22 or 0
        total_rev["age_23_25"] += p.revenue_age_23_25 or 0
        total_rev["age_26_30"] += p.revenue_age_26_30 or 0
        total_rev["age_31_35"] += p.revenue_age_31_35 or 0
        total_rev["age_over_35"] += p.revenue_age_over_35 or 0

    grand_total = sum(total_rev.values()) or 1
    contribution = {k: round(v / grand_total * 100, 2) for k, v in total_rev.items()}

    # 找出贡献最大的年龄段
    top_age = max(contribution, key=contribution.get)
    top_contribution = contribution[top_age]

    age_labels = {
        "age_under_18": "18岁以下",
        "age_18_22": "18-22岁",
        "age_23_25": "23-25岁",
        "age_26_30": "26-30岁",
        "age_31_35": "31-35岁",
        "age_over_35": "35岁以上"
    }

    return {
        "contribution_by_age": contribution,
        "top_age_group": top_age,
        "top_age_label": age_labels.get(top_age, top_age),
        "top_contribution_pct": top_contribution,
        "sample_count": count,
        "insight": f"根据 {count} 家门店的会员数据，{age_labels.get(top_age)} 客群贡献了 {top_contribution:.1f}% 的营收，是核心消费群体。"
    }


def analyze_success_factors(db: Session, tenant_id: int) -> dict:
    """
    分析成功门店与失败门店的差异
    对比面积、机器数、月租金等维度
    """
    success_stores = db.query(Store).filter(
        Store.tenant_id == tenant_id,
        Store.is_success == True
    ).all()

    failed_stores = db.query(Store).filter(
        Store.tenant_id == tenant_id,
        Store.is_success == False
    ).all()

    def avg(stores, attr):
        vals = [getattr(s, attr) for s in stores if getattr(s, attr) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    result = {
        "success_count": len(success_stores),
        "failed_count": len(failed_stores),
        "success_avg": {
            "area_sqm": avg(success_stores, "area_sqm"),
            "machine_count": avg(success_stores, "machine_count"),
            "monthly_rent": avg(success_stores, "monthly_rent"),
        },
        "failed_avg": {
            "area_sqm": avg(failed_stores, "area_sqm"),
            "machine_count": avg(failed_stores, "machine_count"),
            "monthly_rent": avg(failed_stores, "monthly_rent"),
        }
    }

    insights = []
    if result["success_avg"]["area_sqm"] and result["failed_avg"]["area_sqm"]:
        diff = result["success_avg"]["area_sqm"] - result["failed_avg"]["area_sqm"]
        if abs(diff) > 20:
            direction = "更大" if diff > 0 else "更小"
            insights.append(f"成功门店面积平均比失败门店{direction} {abs(diff):.0f}㎡")

    if result["success_avg"]["monthly_rent"] and result["failed_avg"]["monthly_rent"]:
        ratio = result["success_avg"]["monthly_rent"] / (result["failed_avg"]["monthly_rent"] or 1)
        if ratio < 0.8:
            insights.append(f"成功门店月租金平均低于失败门店 {(1-ratio)*100:.0f}%，租金控制是关键因素")

    result["insights"] = insights
    return result


def compute_weight_adjustments(
    member_analysis: dict,
    success_analysis: dict
) -> list:
    """
    根据分析结果计算评分权重调整建议
    返回: [{"dimension": ..., "sub_factor": ..., "suggested_weight": ..., "reason": ...}]
    """
    adjustments = []

    # 基于会员画像调整人口维度权重
    if member_analysis.get("top_age_group"):
        top_age = member_analysis["top_age_group"]
        top_pct = member_analysis.get("top_contribution_pct", 0)

        # 如果某年龄段贡献超过 40%，提升对应人口密度权重
        if top_pct > 40:
            age_to_factor = {
                "age_18_22": "university_density",
                "age_23_25": "young_worker_density",
                "age_26_30": "young_professional_density",
                "age_31_35": "mid_age_density",
            }
            factor = age_to_factor.get(top_age)
            if factor:
                adjustments.append({
                    "dimension": "population",
                    "sub_factor": factor,
                    "suggested_weight": min(0.30, 0.15 + top_pct / 200),
                    "reason": member_analysis.get("insight", "")
                })

    # 基于成功因素分析调整租金维度权重
    if success_analysis.get("success_avg") and success_analysis.get("failed_avg"):
        s_rent = success_analysis["success_avg"].get("monthly_rent")
        f_rent = success_analysis["failed_avg"].get("monthly_rent")
        if s_rent and f_rent and s_rent < f_rent * 0.8:
            adjustments.append({
                "dimension": "rent",
                "sub_factor": "rent_ratio",
                "suggested_weight": 0.20,
                "reason": "历史数据显示租金控制对成功率影响显著，提升租金维度权重"
            })

    return adjustments


def update_scoring_weights(db: Session, tenant_id: int, adjustments: list, upload_record_id: int) -> int:
    """
    将权重调整写入 scoring_rules 表
    返回更新的规则数量
    """
    updated_count = 0
    for adj in adjustments:
        rule = db.query(ScoringRule).filter(
            ScoringRule.tenant_id == tenant_id,
            ScoringRule.dimension == adj["dimension"],
            ScoringRule.sub_factor == adj.get("sub_factor")
        ).first()

        if rule:
            rule.dynamic_weight = adj["suggested_weight"]
            rule.effective_weight = adj["suggested_weight"]
            rule.last_updated_by = "data_analysis"
            rule.update_reason = adj["reason"]
            rule.update_count = (rule.update_count or 0) + 1
            updated_count += 1

    # 标记上传记录已触发权重更新
    if updated_count > 0:
        upload_rec = db.query(UploadRecord).filter(UploadRecord.id == upload_record_id).first()
        if upload_rec:
            upload_rec.weight_updated = True

    db.flush()
    return updated_count


def run_full_analysis(db: Session, tenant_id: int, upload_record_id: int) -> dict:
    """
    完整分析流程:
    1. 分析会员画像影响
    2. 分析成功/失败因素
    3. 计算权重调整建议
    4. 更新评分权重
    5. 生成分析摘要
    """
    logger.info(f"开始分析租户 {tenant_id} 的历史数据...")

    member_analysis = analyze_member_profile_impact(db, tenant_id)
    success_analysis = analyze_success_factors(db, tenant_id)
    adjustments = compute_weight_adjustments(member_analysis, success_analysis)
    updated_count = update_scoring_weights(db, tenant_id, adjustments, upload_record_id)

    # 生成分析摘要文本
    summary_parts = []
    if member_analysis.get("insight"):
        summary_parts.append(f"【会员画像分析】{member_analysis['insight']}")
    if success_analysis.get("insights"):
        for ins in success_analysis["insights"]:
            summary_parts.append(f"【成功因素分析】{ins}")
    if updated_count > 0:
        summary_parts.append(f"【权重更新】根据以上分析，已自动更新 {updated_count} 项评分权重。")
    else:
        summary_parts.append("【权重更新】当前数据量暂不足以触发权重调整，系统将使用默认权重。")

    summary = "\n".join(summary_parts) if summary_parts else "数据量不足，暂无分析结论。"

    # 更新上传记录的分析状态
    upload_rec = db.query(UploadRecord).filter(UploadRecord.id == upload_record_id).first()
    if upload_rec:
        upload_rec.analysis_status = "success"
        upload_rec.analysis_summary = summary

    db.commit()

    # 将历史门店数据和分析结论写入知识库（异步，不阻塞主流程）
    try:
        _schedule_store_vectorization(db, tenant_id, member_analysis, success_analysis, summary)
    except Exception as e:
        logger.warning(f"门店数据向量化调度失败（不影响分析结果）: {e}")

    logger.info(f"分析完成，更新权重 {updated_count} 项")
    return {
        "member_analysis": member_analysis,
        "success_analysis": success_analysis,
        "adjustments": adjustments,
        "updated_weight_count": updated_count,
        "summary": summary
    }


def _schedule_store_vectorization(
    db: Session,
    tenant_id: int,
    member_analysis: dict,
    success_analysis: dict,
    analysis_summary: str,
) -> None:
    """
    将历史门店经验和分析结论写入知识库（同步调用，在后台线程中执行）
    这是"越用越聪明"的关键：每次上传数据后，系统自动学习历史经验
    """
    import asyncio
    import threading

    def _run_async_vectorization():
        """在独立线程中运行异步向量化任务"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_vectorize_stores(tenant_id, member_analysis, success_analysis, analysis_summary))
            loop.close()
        except Exception as e:
            logger.warning(f"后台向量化任务失败: {e}")

    thread = threading.Thread(target=_run_async_vectorization, daemon=True)
    thread.start()
    logger.info(f"已启动后台向量化任务，租户 {tenant_id} 的历史数据将被写入知识库")


async def _vectorize_stores(
    tenant_id: int,
    member_analysis: dict,
    success_analysis: dict,
    analysis_summary: str,
) -> None:
    """
    将历史门店数据和分析结论向量化存入知识库
    使用独立的 db Session（避免与主流程 Session 冲突）
    """
    from app.db.session import SessionLocal
    from app.services.vector_rag import store_text_as_vector
    from app.models.store import Store

    db = SessionLocal()
    try:
        # 1. 向量化各历史门店的经验
        stores = db.query(Store).filter(
            Store.tenant_id == tenant_id,
            Store.experience_notes.isnot(None)
        ).all()

        for store in stores:
            if not store.experience_notes or len(store.experience_notes.strip()) < 10:
                continue

            success_label = "成功门店" if store.is_success else "失败门店"
            content = f"""【历史门店经验】
门店名称：{store.store_name or '未命名'}
地址：{store.address or '未知'}
城市：{store.city or '未知'}
经营状态：{success_label}
面积：{store.area_sqm or '未知'}㎡，机器数：{store.machine_count or '未知'}台，月租金：{store.monthly_rent or '未知'}元
经验总结：{store.experience_notes}"""

            metadata = {
                "type": "store_experience",
                "store_name": store.store_name,
                "address": store.address,
                "city": store.city,
                "is_success": store.is_success,
                "area_sqm": store.area_sqm,
                "monthly_rent": store.monthly_rent,
            }

            await store_text_as_vector(
                content=content,
                metadata=metadata,
                source_type="store_experience",
                source_id=store.id,
                tenant_id=tenant_id,
                db=db,
            )

        # 2. 向量化分析结论（整体洞察）
        if analysis_summary and len(analysis_summary.strip()) > 20:
            import hashlib
            summary_id = int(hashlib.md5(f"{tenant_id}:analysis_summary".encode()).hexdigest()[:8], 16)

            insight_content = f"""【历史数据分析结论】
租户 {tenant_id} 的历史门店分析结论：
{analysis_summary}

会员画像洞察：{member_analysis.get('insight', '暂无')}
成功门店数量：{success_analysis.get('success_count', 0)}，失败门店数量：{success_analysis.get('failed_count', 0)}"""

            await store_text_as_vector(
                content=insight_content,
                metadata={"type": "analysis_insight", "tenant_id": tenant_id},
                source_type="analysis_insight",
                source_id=summary_id,
                tenant_id=tenant_id,
                db=db,
            )

        logger.info(f"租户 {tenant_id} 历史数据向量化完成，共处理 {len(stores)} 家门店")
    except Exception as e:
        logger.error(f"门店数据向量化失败: {e}")
    finally:
        db.close()
