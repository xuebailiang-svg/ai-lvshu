from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user, get_current_superuser, get_db
from app.models.store import AnalysisInsight, DataQualityIssue, DocumentInsight, EvaluationFeedback, ScoringModelVersion, ScoringRule
from app.models.user import User

router = APIRouter()


class ModelVersionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    activate: bool = True


def _tenant_id(user: User) -> int:
    return user.tenant_id or 1


def _current_weight_snapshot(db: Session, tenant_id: int) -> dict:
    rules = db.query(ScoringRule).filter(
        ScoringRule.tenant_id == tenant_id,
        ScoringRule.is_active == True,
    ).all()
    return {
        f"{rule.dimension}.{rule.sub_factor}" if rule.sub_factor else rule.dimension: {
            "dimension": rule.dimension,
            "dimension_name": rule.dimension_name,
            "sub_factor": rule.sub_factor,
            "base_weight": rule.base_weight,
            "dynamic_weight": rule.dynamic_weight,
            "effective_weight": rule.effective_weight,
            "last_updated_by": rule.last_updated_by,
            "update_reason": rule.update_reason,
        }
        for rule in rules
    }


def _source_snapshot(db: Session, tenant_id: int) -> dict:
    approved_insights = db.query(AnalysisInsight).filter(
        AnalysisInsight.tenant_id == tenant_id,
        AnalysisInsight.status == "approved",
    ).all()
    source_counts: dict[str, int] = {}
    for insight in approved_insights:
        source = (insight.evidence or {}).get("source_type") if isinstance(insight.evidence, dict) else None
        source = source or ("historical_data" if insight.insight_type == "factor" else insight.insight_type)
        source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "rule_count": db.query(ScoringRule).filter(ScoringRule.tenant_id == tenant_id, ScoringRule.is_active == True).count(),
        "approved_analysis_insights": len(approved_insights),
        "pending_analysis_insights": db.query(AnalysisInsight).filter(AnalysisInsight.tenant_id == tenant_id, AnalysisInsight.status == "pending").count(),
        "pending_document_insights": db.query(DocumentInsight).filter(DocumentInsight.tenant_id == tenant_id, DocumentInsight.status == "pending").count(),
        "feedback_count": db.query(EvaluationFeedback).filter(EvaluationFeedback.tenant_id == tenant_id).count(),
        "open_data_quality_issues": db.query(DataQualityIssue).filter(DataQualityIssue.tenant_id == tenant_id, DataQualityIssue.status == "open").count(),
        "source_counts": source_counts,
        "created_at": datetime.utcnow().isoformat(),
    }


@router.get("")
def list_model_versions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    items = db.query(ScoringModelVersion).filter(
        ScoringModelVersion.tenant_id == tenant_id
    ).order_by(ScoringModelVersion.created_at.desc()).all()
    if not items:
        snapshot = _current_weight_snapshot(db, tenant_id)
        default = ScoringModelVersion(
            tenant_id=tenant_id,
            name="默认评分模型",
            description="系统根据当前评分权重自动生成的初始模型版本",
            weight_snapshot=snapshot,
            insight_summary="初始模型，尚未经过人工确认的历史分析版本。",
            source_snapshot={**_source_snapshot(db, tenant_id), "generated": "auto"},
            is_active=True,
            created_by=current_user.id,
            activated_by=current_user.id,
            activated_at=datetime.utcnow(),
        )
        db.add(default)
        db.commit()
        db.refresh(default)
        items = [default]
    return {"items": [_payload(item) for item in items]}


@router.post("")
def create_model_version(
    req: ModelVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    tenant_id = _tenant_id(current_user)
    snapshot = _current_weight_snapshot(db, tenant_id)
    if not snapshot:
        raise HTTPException(status_code=400, detail="当前没有可保存的评分权重")
    version = ScoringModelVersion(
        tenant_id=tenant_id,
        name=req.name.strip() or f"评分模型 {datetime.utcnow().strftime('%Y%m%d%H%M')}",
        description=req.description,
        weight_snapshot=snapshot,
        insight_summary=req.description or "由当前已确认权重保存的模型版本。",
        source_snapshot=_source_snapshot(db, tenant_id),
        is_active=False,
        created_by=current_user.id,
    )
    db.add(version)
    db.flush()
    if req.activate:
        _activate(db, tenant_id, version, current_user.id)
    db.commit()
    db.refresh(version)
    return {"message": "模型版本已保存", "item": _payload(version)}


@router.post("/{version_id}/activate")
def activate_model_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    tenant_id = _tenant_id(current_user)
    version = db.query(ScoringModelVersion).filter(
        ScoringModelVersion.id == version_id,
        ScoringModelVersion.tenant_id == tenant_id,
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="模型版本不存在")
    _activate(db, tenant_id, version, current_user.id)
    db.commit()
    return {"message": "模型版本已生效", "item": _payload(version)}


def _activate(db: Session, tenant_id: int, version: ScoringModelVersion, user_id: int) -> None:
    db.query(ScoringModelVersion).filter(ScoringModelVersion.tenant_id == tenant_id).update({"is_active": False})
    version.is_active = True
    version.activated_by = user_id
    version.activated_at = datetime.utcnow()
    snapshot = version.weight_snapshot or {}
    rules = db.query(ScoringRule).filter(ScoringRule.tenant_id == tenant_id, ScoringRule.is_active == True).all()
    for rule in rules:
        key = f"{rule.dimension}.{rule.sub_factor}" if rule.sub_factor else rule.dimension
        data = snapshot.get(key)
        if not data:
            continue
        rule.dynamic_weight = data.get("effective_weight", rule.effective_weight)
        rule.effective_weight = data.get("effective_weight", rule.effective_weight)
        rule.last_updated_by = "model_version"
        rule.update_reason = f"使用模型版本：{version.name}"


def _payload(item: ScoringModelVersion) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "weight_snapshot": item.weight_snapshot,
        "insight_summary": item.insight_summary,
        "source_snapshot": item.source_snapshot,
        "is_active": item.is_active,
        "activated_at": item.activated_at.isoformat() if item.activated_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
