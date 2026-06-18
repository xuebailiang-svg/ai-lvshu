import asyncio
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.store import CrawlEvidenceItem, CrawlJob, EvaluationRecord
from app.models.user import User
from app.services.crawler import (
    _event,
    apply_confirmed_items,
    cancel_external_job,
    crawler_settings,
    regenerate_after_confirmation,
    serialize_item,
    serialize_job,
    start_crawl_job,
    sync_crawl_job,
)


router = APIRouter(tags=["公开信息采集"])

SITE_CATALOG = [
    {"key": "baidu", "label": "百度搜索", "role": "仅发现公开网址", "fields": []},
    {"key": "bing", "label": "Bing 搜索", "role": "仅发现公开网址", "fields": []},
    {"key": "official", "label": "竞品/品牌官网", "role": "公开经营信息", "fields": ["营业时间", "机器配置", "机位数", "面积", "网费", "套餐", "充值", "开业信息"]},
    {"key": "58", "label": "58同城商铺", "role": "公开房源", "fields": ["月租", "租金单价", "面积", "楼层", "地址", "发布时间"]},
    {"key": "anjuke", "label": "安居客商铺", "role": "公开房源", "fields": ["月租", "租金单价", "面积", "楼层", "地址", "发布时间"]},
    {"key": "fang", "label": "房天下商铺", "role": "公开房源", "fields": ["月租", "租金单价", "面积", "楼层", "地址", "发布时间"]},
    {"key": "gov", "label": "*.gov.cn", "role": "政府公开信息", "fields": ["政策原文", "文号", "发布日期", "发布机构"]},
]


class EvidenceDecision(BaseModel):
    item_id: int
    decision: Literal["accepted", "rejected"]
    field_value: Any = None
    review_note: str = Field(default="", max_length=1000)


class ConfirmRequest(BaseModel):
    decisions: list[EvidenceDecision] = Field(min_length=1, max_length=500)


def _job_for_user(db: Session, job_id: int, user: User) -> CrawlJob:
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id, CrawlJob.tenant_id == user.tenant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="采集任务不存在")
    return job


@router.get("/crawl-sources")
def get_crawl_sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfg = crawler_settings(db)
    return {"sites": [{**item, "enabled": item["key"] in cfg["sites"]} for item in SITE_CATALOG]}


@router.get("/evaluate/{evaluation_id}/crawl-job")
async def get_evaluation_crawl_job(evaluation_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = db.query(CrawlJob).filter(
        CrawlJob.evaluation_id == evaluation_id,
        CrawlJob.tenant_id == current_user.tenant_id,
    ).order_by(CrawlJob.id.desc()).first()
    if not job:
        settings = crawler_settings(db)
        return {"job": None, "crawler_enabled": settings["enabled"], "auto_start": settings["auto_start"]}
    job = await sync_crawl_job(db, job)
    counts = {
        status: db.query(CrawlEvidenceItem).filter(CrawlEvidenceItem.crawl_job_id == job.id, CrawlEvidenceItem.status == status).count()
        for status in ("pending", "accepted", "rejected")
    }
    return {"job": serialize_job(job), "item_counts": counts, "crawler_enabled": True}


@router.post("/evaluate/{evaluation_id}/crawl-job/retry", status_code=202)
async def retry_evaluation_crawl_job(evaluation_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == current_user.tenant_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    job = db.query(CrawlJob).filter(CrawlJob.evaluation_id == evaluation_id, CrawlJob.tenant_id == current_user.tenant_id).order_by(CrawlJob.id.desc()).first()
    if not job:
        job = await start_crawl_job(db, record, current_user.id, force=True)
        if not job:
            raise HTTPException(status_code=409, detail="公开信息采集未启用")
        return {"job": serialize_job(job)}
    if job.status not in {"failed", "cancelled", "partial_success", "completed", "regeneration_failed"}:
        raise HTTPException(status_code=409, detail="当前任务仍在执行，不能重试")
    job.retry_count = (job.retry_count or 0) + 1
    job.external_job_id = None
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.finished_at = None
    _event(db, job, "retry", f"用户发起第 {job.retry_count} 次重试")
    db.commit()
    from app.services.crawler import _post_external
    job = await _post_external(db, job, record)
    return {"job": serialize_job(job)}


@router.post("/crawl-jobs/{job_id}/cancel", status_code=202)
async def cancel_crawl_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _job_for_user(db, job_id, current_user)
    try:
        job = await cancel_external_job(db, job)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"job": serialize_job(job)}


@router.get("/crawl-jobs/{job_id}/items")
async def get_crawl_items(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _job_for_user(db, job_id, current_user)
    await sync_crawl_job(db, job)
    items = db.query(CrawlEvidenceItem).filter(CrawlEvidenceItem.crawl_job_id == job.id).order_by(CrawlEvidenceItem.source_type, CrawlEvidenceItem.id).all()
    return {"job": serialize_job(job), "items": [serialize_item(item) for item in items]}


@router.post("/crawl-jobs/{job_id}/confirm", status_code=202)
async def confirm_crawl_items(job_id: int, body: ConfirmRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _job_for_user(db, job_id, current_user)
    if job.status not in {"completed", "partial_success", "failed", "regeneration_failed"}:
        raise HTTPException(status_code=409, detail="任务尚未结束，不能确认结果")
    item_ids = [decision.item_id for decision in body.decisions]
    items = db.query(CrawlEvidenceItem).filter(
        CrawlEvidenceItem.crawl_job_id == job.id,
        CrawlEvidenceItem.id.in_(item_ids),
    ).all()
    by_id = {item.id: item for item in items}
    if len(by_id) != len(set(item_ids)):
        raise HTTPException(status_code=400, detail="包含不属于该任务的证据项")
    pending_ids = {
        row[0] for row in db.query(CrawlEvidenceItem.id).filter(
            CrawlEvidenceItem.crawl_job_id == job.id,
            CrawlEvidenceItem.status == "pending",
        ).all()
    }
    if not pending_ids.issubset(set(item_ids)):
        raise HTTPException(status_code=400, detail="仍有待确认证据，请对全部结果作出采纳或拒绝决定")
    accepted = []
    for decision in body.decisions:
        item = by_id[decision.item_id]
        item.status = decision.decision
        if decision.field_value is not None:
            item.reviewed_value = decision.field_value
        item.review_note = decision.review_note
        item.reviewed_by = current_user.id
        item.reviewed_at = datetime.utcnow()
        if item.status == "accepted":
            accepted.append(item)
    db.flush()
    apply_confirmed_items(db, job, accepted, current_user.id)
    job.status = "regenerating"
    job.progress = 100
    _event(db, job, "confirmed", f"已审核 {len(items)} 条证据，采纳 {len(accepted)} 条；开始生成新版报告")
    db.commit()
    asyncio.create_task(regenerate_after_confirmation(job.id, current_user.id))
    return {"job": serialize_job(job), "accepted": len(accepted), "reviewed": len(items)}
