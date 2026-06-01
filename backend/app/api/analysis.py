from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user, get_db
from app.models.store import (
    AnalysisInsight,
    DataQualityIssue,
    DocumentInsight,
    EvaluationFeedback,
    EvaluationRecord,
    HardwareConfig,
    MemberProfile,
    RevenueRecord,
    ScoringRule,
    Store,
)
from app.models.user import User

router = APIRouter()


class InsightReviewRequest(BaseModel):
    note: str = ""


ASPECT_MAPPING = {
    "交通人流": ("traffic", "交通与人流", "foot_traffic"),
    "竞品判断": ("competition", "竞品分析", "competitor_count"),
    "目标客群": ("population", "目标客群", "young_density"),
    "租金成本": ("rent", "租金与成本", "rent_ratio"),
    "配套设施": ("facility", "配套设施", "commercial_density"),
    "政策风险": ("policy", "政策环境", "policy_risk"),
    "高校数量": ("population", "目标客群", "university_nearby"),
    "报告结论": ("traffic", "交通与人流", "foot_traffic"),
}

SOURCE_LABELS = {
    "historical_data": "历史运营数据",
    "document_experience": "经验文档",
    "evaluation_feedback": "评估反馈",
    "data_quality": "数据质量",
}


def _tenant_id(user: User) -> int:
    return user.tenant_id or 1


def _ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _factor_payload(key: str, name: str, value: float, direction: str, evidence: str, sample_count: int, source_type: str = "historical_data") -> dict:
    return {
        "key": key,
        "name": name,
        "value": round(value, 4),
        "impact_score": round(abs(value) * 100, 1),
        "direction": direction,
        "evidence": evidence,
        "sample_count": sample_count,
        "source_type": source_type,
        "source_label": SOURCE_LABELS.get(source_type, source_type),
    }


def _rule_for(db: Session, tenant_id: int, dimension: str, sub_factor: Optional[str]) -> Optional[ScoringRule]:
    return db.query(ScoringRule).filter(
        ScoringRule.tenant_id == tenant_id,
        ScoringRule.dimension == dimension,
        ScoringRule.sub_factor == sub_factor,
    ).first()


def _bounded_suggested_weight(rule: Optional[ScoringRule], direction: str, strength: float = 0.02) -> Optional[float]:
    if not rule:
        return None
    current = rule.effective_weight if rule.effective_weight is not None else rule.base_weight
    if current is None:
        return None
    delta = min(0.05, max(0.01, strength))
    if direction == "increase":
        return round(max(0.01, min(0.35, current + delta)), 4)
    if direction == "decrease":
        return round(max(0.01, min(0.35, current - delta)), 4)
    return round(current, 4)


def _upsert_insight(
    db: Session,
    tenant_id: int,
    *,
    insight_type: str,
    source_type: str,
    dimension: str,
    dimension_name: str,
    sub_factor: Optional[str],
    title: str,
    summary: str,
    evidence: dict,
    current_weight: Optional[float],
    suggested_weight: Optional[float],
    confidence: float,
    sample_count: int,
) -> None:
    blocked = db.query(AnalysisInsight).filter(
        AnalysisInsight.tenant_id == tenant_id,
        AnalysisInsight.insight_type == insight_type,
        AnalysisInsight.sub_factor == sub_factor,
        AnalysisInsight.title == title,
        AnalysisInsight.status == "deleted",
    ).first()
    if blocked:
        return

    payload = dict(evidence or {})
    payload["source_type"] = source_type
    exists = db.query(AnalysisInsight).filter(
        AnalysisInsight.tenant_id == tenant_id,
        AnalysisInsight.insight_type == insight_type,
        AnalysisInsight.sub_factor == sub_factor,
        AnalysisInsight.title == title,
        AnalysisInsight.status == "pending",
    ).first()
    if exists:
        exists.summary = summary
        exists.evidence = payload
        exists.current_weight = current_weight
        exists.suggested_weight = suggested_weight
        exists.confidence = confidence
        exists.sample_count = sample_count
        exists.updated_at = datetime.utcnow()
        return

    db.add(AnalysisInsight(
        tenant_id=tenant_id,
        insight_type=insight_type,
        dimension=dimension,
        dimension_name=dimension_name,
        sub_factor=sub_factor,
        title=title,
        summary=summary,
        evidence=payload,
        current_weight=current_weight,
        suggested_weight=suggested_weight,
        confidence=confidence,
        sample_count=sample_count,
    ))


def _build_factor_rows(db: Session, tenant_id: int) -> list[dict]:
    revenues = db.query(RevenueRecord).filter(RevenueRecord.tenant_id == tenant_id).all()
    stores = {s.id: s for s in db.query(Store).filter(Store.tenant_id == tenant_id).all()}
    members = {m.store_id: m for m in db.query(MemberProfile).filter(MemberProfile.tenant_id == tenant_id).all()}
    hardware = {h.store_id: h for h in db.query(HardwareConfig).filter(HardwareConfig.tenant_id == tenant_id).all()}
    rows = []
    for rev in revenues:
        store = stores.get(rev.store_id)
        if not store:
            continue
        member = members.get(rev.store_id)
        hw = hardware.get(rev.store_id)
        total_revenue = rev.total_revenue or 0
        rows.append({
            "store_id": rev.store_id,
            "total_revenue": total_revenue,
            "net_profit": rev.net_profit or 0,
            "daily_avg_customers": rev.daily_avg_customers or 0,
            "avg_spend_per_customer": rev.avg_spend_per_customer or 0,
            "rent_cost": rev.rent_cost or store.monthly_rent or 0,
            "machine_count": store.machine_count or 0,
            "area_sqm": store.area_sqm or 0,
            "student_ratio": member.student_ratio if member else 0,
            "age_18_25_ratio": ((member.age_18_22 or 0) + (member.age_23_25 or 0)) if member else 0,
            "vip_private_ratio": _ratio(
                ((hw.vip_seats or 0) + (hw.private_room_seats or 0)),
                ((hw.standard_seats or 0) + (hw.vip_seats or 0) + (hw.private_room_seats or 0)),
            ) if hw else 0,
            "snack_ratio": _ratio(rev.snack_revenue or 0, total_revenue),
            "event_ratio": _ratio(rev.event_revenue or 0, total_revenue),
        })
    return rows


def _feedback_rows(db: Session, tenant_id: int):
    return db.query(EvaluationFeedback, EvaluationRecord).join(
        EvaluationRecord,
        EvaluationRecord.id == EvaluationFeedback.evaluation_id,
    ).filter(
        EvaluationFeedback.tenant_id == tenant_id,
        EvaluationRecord.tenant_id == tenant_id,
        EvaluationRecord.is_excluded == False,
    ).all()


def _pearson(rows: list[dict], x_key: str, y_key: str = "total_revenue") -> Optional[float]:
    pairs = [(float(r.get(x_key) or 0), float(r.get(y_key) or 0)) for r in rows if r.get(x_key) is not None and r.get(y_key) is not None]
    pairs = [(x, y) for x, y in pairs if x != 0 or y != 0]
    if len(pairs) < 2:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    x_avg = sum(xs) / len(xs)
    y_avg = sum(ys) / len(ys)
    numerator = sum((x - x_avg) * (y - y_avg) for x, y in pairs)
    x_den = sum((x - x_avg) ** 2 for x in xs) ** 0.5
    y_den = sum((y - y_avg) ** 2 for y in ys) ** 0.5
    if not x_den or not y_den:
        return None
    return numerator / (x_den * y_den)


def _sync_historical_insights(db: Session, tenant_id: int, factors: list[dict]) -> None:
    mapping = {
        "rent_cost": ("rent", "租金与成本", "rent_ratio"),
        "daily_avg_customers": ("traffic", "交通与人流", "foot_traffic"),
        "avg_spend_per_customer": ("population", "目标客群", "young_density"),
        "machine_count": ("facility", "配套设施", "commercial_density"),
        "age_18_25_ratio": ("population", "目标客群", "university_nearby"),
        "student_ratio": ("population", "目标客群", "university_nearby"),
    }
    for factor in factors[:6]:
        dimension, dimension_name, sub_factor = mapping.get(factor["key"], ("traffic", "交通与人流", None))
        rule = _rule_for(db, tenant_id, dimension, sub_factor)
        current = rule.effective_weight if rule else None
        suggested = current
        if rule:
            direction = "increase" if factor["direction"] == "positive" else "decrease"
            suggested = _bounded_suggested_weight(rule, direction, min(0.05, max(0.01, factor["impact_score"] / 1000)))
        _upsert_insight(
            db,
            tenant_id,
            insight_type="factor",
            source_type="historical_data",
            dimension=dimension,
            dimension_name=dimension_name,
            sub_factor=sub_factor,
            title=factor["name"],
            summary=factor["evidence"],
            evidence=factor,
            current_weight=current,
            suggested_weight=suggested,
            confidence=min(0.9, max(0.35, factor["sample_count"] / 20)),
            sample_count=factor["sample_count"],
        )


def _build_feedback_factor_rows(db: Session, tenant_id: int) -> list[dict]:
    factors: list[dict] = []
    score_revenue_rows = []
    score_customer_rows = []
    customer_gap_rows = []
    for feedback, record in _feedback_rows(db, tenant_id):
        if record.total_score is not None and feedback.actual_monthly_revenue is not None:
            score_revenue_rows.append({"score": record.total_score, "actual_monthly_revenue": feedback.actual_monthly_revenue})
        if record.total_score is not None and feedback.actual_daily_customers is not None:
            score_customer_rows.append({"score": record.total_score, "actual_daily_customers": feedback.actual_daily_customers})
        expected_customers = record.manual_data.get("expected_daily_visitors") if isinstance(record.manual_data, dict) else None
        if expected_customers and feedback.actual_daily_customers is not None:
            try:
                expected = float(expected_customers)
                actual = float(feedback.actual_daily_customers)
                if expected > 0:
                    customer_gap_rows.append({"gap_pct": (actual - expected) / expected})
            except (TypeError, ValueError):
                pass

    corr = _pearson(score_revenue_rows, "score", "actual_monthly_revenue")
    if corr is not None:
        factors.append(_factor_payload(
            "model_score_actual_revenue",
            "模型总分与实际营收",
            corr,
            "positive" if corr >= 0 else "negative",
            f"基于 {len(score_revenue_rows)} 条反馈，模型总分与实际月营收相关系数约为 {corr:.2f}。",
            len(score_revenue_rows),
            "evaluation_feedback",
        ))
    corr = _pearson(score_customer_rows, "score", "actual_daily_customers")
    if corr is not None:
        factors.append(_factor_payload(
            "model_score_actual_customers",
            "模型总分与实际客流",
            corr,
            "positive" if corr >= 0 else "negative",
            f"基于 {len(score_customer_rows)} 条反馈，模型总分与实际日均客流相关系数约为 {corr:.2f}。",
            len(score_customer_rows),
            "evaluation_feedback",
        ))
    if customer_gap_rows:
        avg_gap = sum(row["gap_pct"] for row in customer_gap_rows) / len(customer_gap_rows)
        factors.append(_factor_payload(
            "expected_vs_actual_customers",
            "预测客流偏差",
            avg_gap,
            "positive" if avg_gap >= 0 else "negative",
            f"基于 {len(customer_gap_rows)} 条带预测客流的反馈，实际客流平均偏差 {avg_gap:.1%}。",
            len(customer_gap_rows),
            "evaluation_feedback",
        ))
    return factors


def sync_feedback_and_quality_insights(db: Session, tenant_id: int) -> None:
    feedback_rows = _feedback_rows(db, tenant_id)
    inaccurate_counts: dict[str, int] = {}
    accurate_counts: dict[str, int] = {}
    customer_gap_rows = []
    for feedback, record in feedback_rows:
        for aspect in feedback.inaccurate_aspects or []:
            inaccurate_counts[str(aspect)] = inaccurate_counts.get(str(aspect), 0) + 1
        for aspect in feedback.accurate_aspects or []:
            accurate_counts[str(aspect)] = accurate_counts.get(str(aspect), 0) + 1
        expected_customers = record.manual_data.get("expected_daily_visitors") if isinstance(record.manual_data, dict) else None
        if expected_customers and feedback.actual_daily_customers is not None:
            try:
                expected = float(expected_customers)
                actual = float(feedback.actual_daily_customers)
                if expected > 0:
                    customer_gap_rows.append({
                        "record_id": record.id,
                        "address": record.address,
                        "expected": expected,
                        "actual": actual,
                        "gap_pct": (actual - expected) / expected,
                    })
            except (TypeError, ValueError):
                pass

    for aspect, count in inaccurate_counts.items():
        dimension, dimension_name, sub_factor = ASPECT_MAPPING.get(aspect, ("traffic", "交通与人流", "foot_traffic"))
        rule = _rule_for(db, tenant_id, dimension, sub_factor)
        _upsert_insight(
            db, tenant_id,
            insight_type="feedback_review",
            source_type="evaluation_feedback",
            dimension=dimension,
            dimension_name=dimension_name,
            sub_factor=sub_factor,
            title=f"反馈显示{aspect}判断需校准",
            summary=f"评估反馈中有 {count} 次认为“{aspect}”判断不准确，建议降低该因素对最终评分的影响，并复核相关数据源。",
            evidence={"aspect": aspect, "inaccurate_count": count, "feedback_count": len(feedback_rows), "direction": "decrease"},
            current_weight=rule.effective_weight if rule else None,
            suggested_weight=_bounded_suggested_weight(rule, "decrease", min(0.05, 0.015 + count * 0.005)),
            confidence=min(0.9, max(0.45, count / max(3, len(feedback_rows)))),
            sample_count=count,
        )

    for aspect, count in accurate_counts.items():
        if count < 2:
            continue
        dimension, dimension_name, sub_factor = ASPECT_MAPPING.get(aspect, ("traffic", "交通与人流", "foot_traffic"))
        rule = _rule_for(db, tenant_id, dimension, sub_factor)
        _upsert_insight(
            db, tenant_id,
            insight_type="feedback_review",
            source_type="evaluation_feedback",
            dimension=dimension,
            dimension_name=dimension_name,
            sub_factor=sub_factor,
            title=f"反馈显示{aspect}判断较稳定",
            summary=f"评估反馈中有 {count} 次认为“{aspect}”判断准确，说明该因素当前解释力较好，可小幅提高或保持权重。",
            evidence={"aspect": aspect, "accurate_count": count, "feedback_count": len(feedback_rows), "direction": "increase"},
            current_weight=rule.effective_weight if rule else None,
            suggested_weight=_bounded_suggested_weight(rule, "increase", min(0.03, 0.01 + count * 0.003)),
            confidence=min(0.85, max(0.4, count / max(4, len(feedback_rows)))),
            sample_count=count,
        )

    underperformed = [row for row in customer_gap_rows if row["gap_pct"] <= -0.25]
    overperformed = [row for row in customer_gap_rows if row["gap_pct"] >= 0.25]
    if underperformed:
        rule = _rule_for(db, tenant_id, "traffic", "foot_traffic")
        avg_gap = sum(row["gap_pct"] for row in underperformed) / len(underperformed)
        _upsert_insight(
            db, tenant_id,
            insight_type="model_review",
            source_type="evaluation_feedback",
            dimension="traffic",
            dimension_name="交通与人流",
            sub_factor="foot_traffic",
            title="实际客流低于预测，需降低乐观估计",
            summary=f"{len(underperformed)} 个评估反馈的实际日均客流低于预测 25% 以上，平均偏差 {avg_gap:.1%}，建议降低人流估计权重或提高数据质量门槛。",
            evidence={"gap_rows": underperformed[:10], "direction": "decrease"},
            current_weight=rule.effective_weight if rule else None,
            suggested_weight=_bounded_suggested_weight(rule, "decrease", 0.03),
            confidence=min(0.9, max(0.45, len(underperformed) / max(3, len(customer_gap_rows)))),
            sample_count=len(underperformed),
        )
    if overperformed:
        rule = _rule_for(db, tenant_id, "traffic", "foot_traffic")
        avg_gap = sum(row["gap_pct"] for row in overperformed) / len(overperformed)
        _upsert_insight(
            db, tenant_id,
            insight_type="model_review",
            source_type="evaluation_feedback",
            dimension="traffic",
            dimension_name="交通与人流",
            sub_factor="foot_traffic",
            title="实际客流高于预测，可复核低估因素",
            summary=f"{len(overperformed)} 个评估反馈的实际日均客流高于预测 25% 以上，平均偏差 {avg_gap:.1%}，建议复核是否低估交通、人群或商圈热度。",
            evidence={"gap_rows": overperformed[:10], "direction": "increase"},
            current_weight=rule.effective_weight if rule else None,
            suggested_weight=_bounded_suggested_weight(rule, "increase", 0.02),
            confidence=min(0.85, max(0.4, len(overperformed) / max(3, len(customer_gap_rows)))),
            sample_count=len(overperformed),
        )

    open_issues = db.query(DataQualityIssue).filter(
        DataQualityIssue.tenant_id == tenant_id,
        DataQualityIssue.status == "open",
    ).all()
    issue_groups: dict[str, list[DataQualityIssue]] = {}
    for issue in open_issues:
        if "university" in (issue.issue_type or "") or "poi" in (issue.issue_type or ""):
            key = "population.university_nearby"
        elif "competitor" in (issue.issue_type or ""):
            key = "competition.competitor_count"
        else:
            key = "traffic.foot_traffic"
        issue_groups.setdefault(key, []).append(issue)

    active_quality_titles = set()
    for key, issues in issue_groups.items():
        dimension, sub_factor = key.split(".", 1)
        dimension_name = {"population": "目标客群", "competition": "竞品分析", "traffic": "交通与人流"}.get(dimension, dimension)
        rule = _rule_for(db, tenant_id, dimension, sub_factor)
        title = f"{dimension_name}存在未解决数据质量问题"
        active_quality_titles.add(title)
        _upsert_insight(
            db, tenant_id,
            insight_type="data_quality_review",
            source_type="data_quality",
            dimension=dimension,
            dimension_name=dimension_name,
            sub_factor=sub_factor,
            title=title,
            summary=f"当前有 {len(issues)} 条未解决的数据质量问题影响 {dimension_name}，建议在问题处理前降低该因素可信度。",
            evidence={"issue_ids": [issue.id for issue in issues[:20]], "issue_count": len(issues), "direction": "decrease"},
            current_weight=rule.effective_weight if rule else None,
            suggested_weight=_bounded_suggested_weight(rule, "decrease", min(0.04, 0.01 + len(issues) * 0.004)),
            confidence=min(0.85, max(0.45, len(issues) / 5)),
            sample_count=len(issues),
        )

    stale_quality = db.query(AnalysisInsight).filter(
        AnalysisInsight.tenant_id == tenant_id,
        AnalysisInsight.insight_type == "data_quality_review",
        AnalysisInsight.status == "pending",
    ).all()
    for insight in stale_quality:
        if insight.title not in active_quality_titles:
            insight.status = "rejected"
            insight.review_note = "相关数据质量问题已处理，自动关闭待确认建议"
            insight.reviewed_at = datetime.utcnow()


@router.get("/overview")
def get_analysis_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()

    store_count = db.query(Store).filter(Store.tenant_id == tenant_id).count()
    revenue_count = db.query(RevenueRecord).filter(RevenueRecord.tenant_id == tenant_id).count()
    member_count = db.query(MemberProfile).filter(MemberProfile.tenant_id == tenant_id).count()
    hardware_count = db.query(HardwareConfig).filter(HardwareConfig.tenant_id == tenant_id).count()
    feedback_count = db.query(EvaluationFeedback).filter(EvaluationFeedback.tenant_id == tenant_id).count()
    feedback_actual_count = db.query(EvaluationFeedback).filter(
        EvaluationFeedback.tenant_id == tenant_id,
        or_(
            EvaluationFeedback.actual_daily_customers.isnot(None),
            EvaluationFeedback.actual_monthly_revenue.isnot(None),
            EvaluationFeedback.actual_monthly_profit.isnot(None),
        ),
    ).count()
    quality_open_count = db.query(DataQualityIssue).filter(DataQualityIssue.tenant_id == tenant_id, DataQualityIssue.status == "open").count()
    quality_total_count = db.query(DataQualityIssue).filter(DataQualityIssue.tenant_id == tenant_id).count()
    pending_insights = db.query(AnalysisInsight).filter(AnalysisInsight.tenant_id == tenant_id, AnalysisInsight.status == "pending").count()
    pending_document_insights = db.query(DocumentInsight).filter(DocumentInsight.tenant_id == tenant_id, DocumentInsight.status == "pending").count()
    avg_revenue = db.query(func.avg(RevenueRecord.total_revenue)).filter(RevenueRecord.tenant_id == tenant_id).scalar() or 0
    avg_profit = db.query(func.avg(RevenueRecord.net_profit)).filter(RevenueRecord.tenant_id == tenant_id).scalar() or 0
    avg_actual_revenue = db.query(func.avg(EvaluationFeedback.actual_monthly_revenue)).filter(EvaluationFeedback.tenant_id == tenant_id).scalar() or 0
    avg_actual_customers = db.query(func.avg(EvaluationFeedback.actual_daily_customers)).filter(EvaluationFeedback.tenant_id == tenant_id).scalar() or 0
    return {
        "samples": {
            "stores": store_count,
            "revenue_records": revenue_count,
            "member_profiles": member_count,
            "hardware_configs": hardware_count,
            "evaluation_feedback": feedback_count,
            "feedback_actuals": feedback_actual_count,
            "data_quality_issues": quality_total_count,
        },
        "summary": {
            "avg_revenue": round(float(avg_revenue), 2),
            "avg_profit": round(float(avg_profit), 2),
            "avg_actual_revenue": round(float(avg_actual_revenue), 2),
            "avg_actual_daily_customers": round(float(avg_actual_customers), 2),
            "pending_insights": pending_insights,
            "pending_document_insights": pending_document_insights,
            "open_data_quality_issues": quality_open_count,
        },
    }


@router.get("/factors")
def get_analysis_factors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    rows = _build_factor_rows(db, tenant_id)
    factor_names = {
        "rent_cost": "租金成本",
        "machine_count": "机器数量",
        "area_sqm": "门店面积",
        "daily_avg_customers": "日均客流",
        "avg_spend_per_customer": "客单价",
        "student_ratio": "学生客群占比",
        "age_18_25_ratio": "18-25 岁客群占比",
        "vip_private_ratio": "VIP/包间座位占比",
        "snack_ratio": "水吧零食收入占比",
        "event_ratio": "赛事活动收入占比",
    }
    factors = []
    for key, name in factor_names.items():
        corr = _pearson(rows, key)
        if corr is None:
            continue
        direction = "positive" if corr >= 0 else "negative"
        evidence = f"基于 {len(rows)} 条营收样本，{name} 与总营收的相关系数约为 {corr:.2f}。"
        factors.append(_factor_payload(key, name, corr, direction, evidence, len(rows), "historical_data"))
    factors.sort(key=lambda item: item["impact_score"], reverse=True)
    _sync_historical_insights(db, tenant_id, factors)
    feedback_factors = _build_feedback_factor_rows(db, tenant_id)
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    return {
        "items": factors,
        "feedback_items": feedback_factors,
        "sample_count": len(rows),
        "feedback_sample_count": len(_feedback_rows(db, tenant_id)),
    }


@router.get("/insights")
def list_analysis_insights(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    query = db.query(AnalysisInsight).filter(AnalysisInsight.tenant_id == tenant_id)
    if status:
        query = query.filter(AnalysisInsight.status == status)
    else:
        query = query.filter(AnalysisInsight.status != "deleted")
    items = query.order_by(AnalysisInsight.created_at.desc()).limit(100).all()
    return {"items": [_insight_payload(item) for item in items]}


@router.post("/insights/{insight_id}/approve")
def approve_analysis_insight(
    insight_id: int,
    req: InsightReviewRequest = InsightReviewRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    insight = db.query(AnalysisInsight).filter(AnalysisInsight.id == insight_id, AnalysisInsight.tenant_id == tenant_id).first()
    if not insight:
        raise HTTPException(status_code=404, detail="分析建议不存在")
    if insight.status != "pending":
        raise HTTPException(status_code=400, detail="该建议已经处理")
    if insight.suggested_weight is not None and insight.dimension:
        rule = _rule_for(db, tenant_id, insight.dimension, insight.sub_factor)
        if rule:
            rule.dynamic_weight = insight.suggested_weight
            rule.effective_weight = insight.suggested_weight
            rule.last_updated_by = "analysis_review"
            rule.update_reason = insight.summary
            rule.update_count = (rule.update_count or 0) + 1
    insight.status = "approved"
    insight.review_note = req.note
    insight.reviewed_by = current_user.id
    insight.reviewed_at = datetime.utcnow()
    db.commit()
    return {"message": "分析建议已确认", "insight": _insight_payload(insight)}


@router.post("/insights/{insight_id}/reject")
def reject_analysis_insight(
    insight_id: int,
    req: InsightReviewRequest = InsightReviewRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    insight = db.query(AnalysisInsight).filter(AnalysisInsight.id == insight_id, AnalysisInsight.tenant_id == tenant_id).first()
    if not insight:
        raise HTTPException(status_code=404, detail="分析建议不存在")
    if insight.status != "pending":
        raise HTTPException(status_code=400, detail="该建议已经处理")
    insight.status = "rejected"
    insight.review_note = req.note
    insight.reviewed_by = current_user.id
    insight.reviewed_at = datetime.utcnow()
    db.commit()
    return {"message": "分析建议已忽略", "insight": _insight_payload(insight)}


@router.delete("/insights/{insight_id}")
def delete_analysis_insight(
    insight_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    insight = db.query(AnalysisInsight).filter(
        AnalysisInsight.id == insight_id,
        AnalysisInsight.tenant_id == tenant_id,
    ).first()
    if not insight:
        raise HTTPException(status_code=404, detail="分析建议不存在")
    insight.status = "deleted"
    insight.review_note = "用户删除"
    insight.reviewed_by = current_user.id
    insight.reviewed_at = datetime.utcnow()
    db.commit()
    return {"message": "分析建议已删除"}


def _insight_payload(item: AnalysisInsight) -> dict:
    source_type = (item.evidence or {}).get("source_type") if isinstance(item.evidence, dict) else None
    if not source_type:
        source_type = "historical_data" if item.insight_type == "factor" else item.insight_type
    return {
        "id": item.id,
        "insight_type": item.insight_type,
        "source_type": source_type,
        "source_label": SOURCE_LABELS.get(source_type, source_type),
        "dimension": item.dimension,
        "dimension_name": item.dimension_name,
        "sub_factor": item.sub_factor,
        "title": item.title,
        "summary": item.summary,
        "evidence": item.evidence,
        "current_weight": item.current_weight,
        "suggested_weight": item.suggested_weight,
        "confidence": item.confidence,
        "sample_count": item.sample_count,
        "status": item.status,
        "review_note": item.review_note,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
