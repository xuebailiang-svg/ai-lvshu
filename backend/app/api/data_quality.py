from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user, get_db
from app.models.store import DataQualityIssue, EvaluationFeedback, EvaluationRecord, ExcludedKnowledgeSource
from app.models.user import User
from app.api.analysis import sync_feedback_and_quality_insights

router = APIRouter()


class IssueCreate(BaseModel):
    evaluation_id: Optional[int] = None
    source_type: str = "evaluation_result"
    source_id: Optional[int] = None
    issue_type: str = "user_marked_abnormal"
    severity: str = "warning"
    title: str
    description: Optional[str] = None
    payload: Optional[dict] = None


class ResolveRequest(BaseModel):
    note: str = ""


class ExcludeRequest(BaseModel):
    source_type: str = "evaluation_result"
    source_id: int
    reason: str = ""


def _tenant_id(user: User) -> int:
    return user.tenant_id or 1


@router.post("/issues")
def create_issue(
    req: IssueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    source_id = req.source_id or req.evaluation_id
    issue = DataQualityIssue(
        tenant_id=tenant_id,
        evaluation_id=req.evaluation_id,
        source_type=req.source_type,
        source_id=source_id,
        issue_type=req.issue_type,
        severity=req.severity,
        title=req.title,
        description=req.description,
        payload=req.payload,
        created_by=current_user.id,
    )
    db.add(issue)
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    db.refresh(issue)
    return {"message": "数据质量问题已记录", "issue": _issue_payload(issue)}


@router.get("/issues")
def list_issues(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    query = db.query(DataQualityIssue).filter(DataQualityIssue.tenant_id == tenant_id)
    if status:
        query = query.filter(DataQualityIssue.status == status)
    items = query.order_by(DataQualityIssue.created_at.desc()).limit(200).all()
    return {"items": [_issue_payload(item) for item in items]}


@router.post("/issues/{issue_id}/resolve")
def resolve_issue(
    issue_id: int,
    req: ResolveRequest = ResolveRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    issue = db.query(DataQualityIssue).filter(DataQualityIssue.id == issue_id, DataQualityIssue.tenant_id == tenant_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="数据质量问题不存在")
    issue.status = "resolved"
    issue.resolution_note = req.note
    issue.resolved_by = current_user.id
    issue.resolved_at = datetime.utcnow()
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    return {"message": "数据质量问题已处理", "issue": _issue_payload(issue)}


@router.delete("/issues/{issue_id}")
def delete_issue(
    issue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    issue = db.query(DataQualityIssue).filter(
        DataQualityIssue.id == issue_id,
        DataQualityIssue.tenant_id == tenant_id,
    ).first()
    if not issue:
        raise HTTPException(status_code=404, detail="数据质量问题不存在")
    db.delete(issue)
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    return {"message": "数据质量问题已删除"}


@router.post("/sources/{source_id}/exclude")
def exclude_source(
    source_id: int,
    req: ExcludeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    existing = db.query(ExcludedKnowledgeSource).filter(
        ExcludedKnowledgeSource.tenant_id == tenant_id,
        ExcludedKnowledgeSource.source_type == req.source_type,
        ExcludedKnowledgeSource.source_id == source_id,
    ).first()
    if not existing:
        existing = ExcludedKnowledgeSource(
            tenant_id=tenant_id,
            source_type=req.source_type,
            source_id=source_id,
            reason=req.reason,
            excluded_by=current_user.id,
        )
        db.add(existing)
    else:
        existing.reason = req.reason or existing.reason

    if req.source_type == "evaluation_result":
        record = db.query(EvaluationRecord).filter(EvaluationRecord.id == source_id, EvaluationRecord.tenant_id == tenant_id).first()
        if record:
            record.is_excluded = True
            record.exclude_reason = req.reason
            record.excluded_by = current_user.id
            record.excluded_at = datetime.utcnow()

    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    return {"message": "来源已排除，后续不会参与 RAG、相似案例和报告引用"}


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: int,
    source_type: str = "evaluation_result",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = _tenant_id(current_user)
    if source_type == "evaluation_result":
        record = db.query(EvaluationRecord).filter(EvaluationRecord.id == source_id, EvaluationRecord.tenant_id == tenant_id).first()
        if record:
            db.query(EvaluationFeedback).filter(EvaluationFeedback.evaluation_id == source_id, EvaluationFeedback.tenant_id == tenant_id).delete()
            db.query(DataQualityIssue).filter(DataQualityIssue.evaluation_id == source_id, DataQualityIssue.tenant_id == tenant_id).delete()
            db.query(ExcludedKnowledgeSource).filter(
                ExcludedKnowledgeSource.tenant_id == tenant_id,
                ExcludedKnowledgeSource.source_type == source_type,
                ExcludedKnowledgeSource.source_id == source_id,
            ).delete()
            db.delete(record)
        else:
            raise HTTPException(status_code=404, detail="历史评估案例不存在")
    try:
        db.execute(text("""
            DELETE FROM knowledge_vectors
            WHERE tenant_id = :tenant_id AND source_type = :source_type AND source_id = :source_id
        """), {"tenant_id": tenant_id, "source_type": source_type, "source_id": source_id})
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="知识库删除失败")
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    return {"message": "来源已彻底删除"}


def _issue_payload(item: DataQualityIssue) -> dict:
    return {
        "id": item.id,
        "evaluation_id": item.evaluation_id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "issue_type": item.issue_type,
        "severity": item.severity,
        "title": item.title,
        "description": item.description,
        "payload": item.payload,
        "status": item.status,
        "resolution_note": item.resolution_note,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
    }
