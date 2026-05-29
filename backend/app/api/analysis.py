from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user, get_db
from app.models.store import (
    AnalysisInsight,
    DocumentInsight,
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


def _tenant_id(user: User) -> int:
    return user.tenant_id or 1


def _ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _factor_payload(key: str, name: str, value: float, direction: str, evidence: str, sample_count: int) -> dict:
    return {
        "key": key,
        "name": name,
        "value": round(value, 4),
        "impact_score": round(abs(value) * 100, 1),
        "direction": direction,
        "evidence": evidence,
        "sample_count": sample_count,
    }


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
            "vip_private_ratio": _ratio(((hw.vip_seats or 0) + (hw.private_room_seats or 0)), ((hw.standard_seats or 0) + (hw.vip_seats or 0) + (hw.private_room_seats or 0))) if hw else 0,
            "snack_ratio": _ratio(rev.snack_revenue or 0, total_revenue),
            "event_ratio": _ratio(rev.event_revenue or 0, total_revenue),
        })
    return rows


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


def _sync_analysis_insights(db: Session, tenant_id: int, factors: list[dict]) -> None:
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
        rule = db.query(ScoringRule).filter(
            ScoringRule.tenant_id == tenant_id,
            ScoringRule.dimension == dimension,
            ScoringRule.sub_factor == sub_factor,
        ).first()
        current_weight = rule.effective_weight if rule else None
        suggested_weight = current_weight
        if current_weight is not None:
            delta = min(0.05, max(0.01, factor["impact_score"] / 1000))
            suggested_weight = max(0.01, min(0.35, current_weight + delta if factor["direction"] == "positive" else current_weight - delta))

        blocked = db.query(AnalysisInsight).filter(
            AnalysisInsight.tenant_id == tenant_id,
            AnalysisInsight.insight_type == "factor",
            AnalysisInsight.sub_factor == sub_factor,
            AnalysisInsight.title == factor["name"],
            AnalysisInsight.status == "deleted",
        ).first()
        if blocked:
            continue

        exists = db.query(AnalysisInsight).filter(
            AnalysisInsight.tenant_id == tenant_id,
            AnalysisInsight.insight_type == "factor",
            AnalysisInsight.sub_factor == sub_factor,
            AnalysisInsight.title == factor["name"],
            AnalysisInsight.status == "pending",
        ).first()
        if exists:
            exists.summary = factor["evidence"]
            exists.evidence = factor
            exists.current_weight = current_weight
            exists.suggested_weight = suggested_weight
            exists.confidence = min(0.9, max(0.35, factor["sample_count"] / 20))
            exists.sample_count = factor["sample_count"]
            continue

        db.add(AnalysisInsight(
            tenant_id=tenant_id,
            insight_type="factor",
            dimension=dimension,
            dimension_name=dimension_name,
            sub_factor=sub_factor,
            title=factor["name"],
            summary=factor["evidence"],
            evidence=factor,
            current_weight=current_weight,
            suggested_weight=suggested_weight,
            confidence=min(0.9, max(0.35, factor["sample_count"] / 20)),
            sample_count=factor["sample_count"],
        ))
    db.flush()


@router.get("/overview")
def get_analysis_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    store_count = db.query(Store).filter(Store.tenant_id == tenant_id).count()
    revenue_count = db.query(RevenueRecord).filter(RevenueRecord.tenant_id == tenant_id).count()
    member_count = db.query(MemberProfile).filter(MemberProfile.tenant_id == tenant_id).count()
    hardware_count = db.query(HardwareConfig).filter(HardwareConfig.tenant_id == tenant_id).count()
    pending_insights = db.query(AnalysisInsight).filter(AnalysisInsight.tenant_id == tenant_id, AnalysisInsight.status == "pending").count()
    pending_document_insights = db.query(DocumentInsight).filter(DocumentInsight.tenant_id == tenant_id, DocumentInsight.status == "pending").count()
    avg_revenue = db.query(func.avg(RevenueRecord.total_revenue)).filter(RevenueRecord.tenant_id == tenant_id).scalar() or 0
    avg_profit = db.query(func.avg(RevenueRecord.net_profit)).filter(RevenueRecord.tenant_id == tenant_id).scalar() or 0
    return {
        "samples": {
            "stores": store_count,
            "revenue_records": revenue_count,
            "member_profiles": member_count,
            "hardware_configs": hardware_count,
        },
        "summary": {
            "avg_revenue": round(float(avg_revenue), 2),
            "avg_profit": round(float(avg_profit), 2),
            "pending_insights": pending_insights,
            "pending_document_insights": pending_document_insights,
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
        factors.append(_factor_payload(key, name, corr, direction, evidence, len(rows)))
    factors.sort(key=lambda item: item["impact_score"], reverse=True)
    _sync_analysis_insights(db, tenant_id, factors)
    db.commit()
    return {"items": factors, "sample_count": len(rows)}


@router.get("/insights")
def list_analysis_insights(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
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
        rule = db.query(ScoringRule).filter(
            ScoringRule.tenant_id == tenant_id,
            ScoringRule.dimension == insight.dimension,
            ScoringRule.sub_factor == insight.sub_factor,
        ).first()
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
    return {
        "id": item.id,
        "insight_type": item.insight_type,
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
