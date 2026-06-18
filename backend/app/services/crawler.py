"""Main-backend integration for the isolated public-information crawler."""
import asyncio
import ipaddress
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_config_value
from app.db.session import SessionLocal
from app.models.store import (
    CompetitorObservation,
    CompetitorProfile,
    CrawlEvidenceItem,
    CrawlJob,
    CrawlJobEvent,
    EvaluationRecord,
)
from app.models.system_config import SystemConfig
from app.services.crawl_merge import merge_competitor_rows, merge_property_conditions
from app.services.scoring import evaluate_location


logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"completed", "partial_success", "failed", "cancelled", "regenerated"}


def _configs(db: Session) -> dict[str, str]:
    rows = db.query(SystemConfig).filter(
        SystemConfig.config_key.like("crawler.%"),
        SystemConfig.is_active == True,
    ).all()
    return {row.config_key: (decrypt_config_value(row.config_value) if row.config_value else "") for row in rows}


def _enabled(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def crawler_settings(db: Session) -> dict:
    cfg = _configs(db)
    source_flags = {
        key: _enabled(cfg.get(f"crawler.source.{key}"), True)
        for key in ("official", "property", "government")
    }
    sites = [
        key for key in ("baidu", "bing", "official", "58", "anjuke", "fang", "gov")
        if _enabled(cfg.get(f"crawler.site.{key}"), True)
    ]
    if not source_flags["official"] and "official" in sites:
        sites.remove("official")
    if not source_flags["property"]:
        sites = [key for key in sites if key not in {"58", "anjuke", "fang"}]
    if not source_flags["government"] and "gov" in sites:
        sites.remove("gov")
    return {
        "enabled": _enabled(cfg.get("crawler.enabled")),
        "auto_start": _enabled(cfg.get("crawler.auto_start"), True),
        "service_url": cfg.get("crawler.service_url", "http://127.0.0.1:8010").rstrip("/"),
        "token": cfg.get("crawler.internal_token", ""),
        "max_pages": min(max(int(cfg.get("crawler.max_pages") or 20), 1), 20),
        "timeout_seconds": min(max(int(cfg.get("crawler.timeout_seconds") or 300), 30), 300),
        "sources": [key for key, enabled in source_flags.items() if enabled],
        "sites": sites,
    }


def _is_loopback_service_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def serialize_job(job: CrawlJob) -> dict:
    return {
        "id": job.id,
        "evaluation_id": job.evaluation_id,
        "external_job_id": job.external_job_id,
        "status": job.status,
        "progress": job.progress or 0,
        "source_scope": job.source_scope or {},
        "error_message": job.error_message,
        "retry_count": job.retry_count or 0,
        "regenerated_evaluation_id": job.regenerated_evaluation_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def serialize_item(item: CrawlEvidenceItem) -> dict:
    return {
        "id": item.id,
        "source_type": item.source_type,
        "source_site": item.source_site,
        "source_domain": item.source_domain,
        "source_url": item.source_url,
        "target_name": item.target_name,
        "field_name": item.field_name,
        "field_value": item.reviewed_value if item.reviewed_value is not None else item.field_value,
        "original_value": item.field_value,
        "evidence_text": item.evidence_text,
        "confidence": item.confidence,
        "status": item.status,
        "review_note": item.review_note,
        "collected_at": item.collected_at.isoformat() if item.collected_at else None,
    }


def _event(db: Session, job: CrawlJob, event_type: str, message: str, payload: Optional[dict] = None) -> None:
    db.add(CrawlJobEvent(
        tenant_id=job.tenant_id,
        crawl_job_id=job.id,
        event_type=event_type,
        message=message,
        payload=payload or {},
    ))


async def _post_external(db: Session, job: CrawlJob, record: EvaluationRecord) -> CrawlJob:
    cfg = crawler_settings(db)
    if not cfg["token"]:
        job.status = "failed"
        job.error_message = "CRAWLER_INTERNAL_TOKEN_NOT_CONFIGURED"
        _event(db, job, "failed", "采集服务 Token 未配置")
        db.commit()
        return job
    if not _is_loopback_service_url(cfg["service_url"]):
        job.status = "failed"
        job.error_message = "CRAWLER_SERVICE_URL_MUST_BE_LOOPBACK"
        _event(db, job, "failed", "采集服务地址必须使用 localhost/127.0.0.1/::1")
        db.commit()
        return job
    payload = {
        "evaluation_id": record.id,
        "attempt": job.retry_count or 0,
        "address": record.address,
        "city": "",
        "keywords": [],
        "sources": cfg["sources"],
        "sites": cfg["sites"],
        "seed_urls": [],
        "max_pages": cfg["max_pages"],
        "timeout_seconds": cfg["timeout_seconds"],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{cfg['service_url']}/v1/jobs",
                headers={"Authorization": f"Bearer {cfg['token']}"},
                json=payload,
            )
            response.raise_for_status()
        external = response.json()
        job.external_job_id = external["job_id"]
        job.status = external.get("status", "queued")
        job.progress = 0
        job.error_message = None
        _event(db, job, "queued", "公开信息采集任务已提交到内部服务")
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"CRAWLER_SERVICE_UNAVAILABLE: {str(exc)[:300]}"
        _event(db, job, "failed", "采集服务不可用，初版报告不受影响", {"error": str(exc)[:200]})
    db.commit()
    db.refresh(job)
    return job


async def start_crawl_job(db: Session, record: EvaluationRecord, created_by: Optional[int], force: bool = False) -> Optional[CrawlJob]:
    cfg = crawler_settings(db)
    if not cfg["enabled"] or (not force and not cfg["auto_start"]):
        return None
    existing = db.query(CrawlJob).filter(
        CrawlJob.tenant_id == record.tenant_id,
        CrawlJob.evaluation_id == record.id,
    ).order_by(CrawlJob.id.desc()).first()
    if existing:
        return existing
    job = CrawlJob(
        tenant_id=record.tenant_id,
        evaluation_id=record.id,
        status="queued",
        progress=0,
        source_scope={"sources": cfg["sources"], "sites": cfg["sites"], "max_pages": cfg["max_pages"]},
        created_by=created_by,
    )
    db.add(job)
    db.flush()
    _event(db, job, "created", "主系统已创建公开信息采集任务")
    db.commit()
    db.refresh(job)
    return await _post_external(db, job, record)


async def auto_start_crawl(evaluation_id: int, tenant_id: int, created_by: Optional[int]) -> None:
    db = SessionLocal()
    try:
        record = db.query(EvaluationRecord).filter(
            EvaluationRecord.id == evaluation_id,
            EvaluationRecord.tenant_id == tenant_id,
        ).first()
        if record:
            await start_crawl_job(db, record, created_by)
    except Exception:
        logger.exception("自动创建公开信息采集任务失败，evaluation_id=%s", evaluation_id)
    finally:
        db.close()


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def sync_crawl_job(db: Session, job: CrawlJob) -> CrawlJob:
    if not job.external_job_id or job.status in {"regenerating", "regenerated"}:
        return job
    cfg = crawler_settings(db)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{cfg['service_url']}/v1/jobs/{job.external_job_id}",
                headers={"Authorization": f"Bearer {cfg['token']}"},
            )
            response.raise_for_status()
        remote = response.json()
    except Exception as exc:
        job.error_message = f"STATUS_SYNC_FAILED: {str(exc)[:300]}"
        db.commit()
        return job

    previous_status = job.status
    job.status = remote.get("status", job.status)
    job.progress = int(remote.get("progress") or 0)
    job.started_at = _parse_datetime(remote.get("started_at")) or job.started_at
    job.finished_at = _parse_datetime(remote.get("finished_at")) or job.finished_at
    errors = remote.get("errors") or []
    if errors:
        job.error_message = "; ".join(str(item.get("error", "")) for item in errors[-3:])[:1000]
    scope = dict(job.source_scope or {})
    scope["source_progress"] = remote.get("source_progress") or scope.get("source_progress") or {}
    synced_events = int(scope.get("synced_event_count") or 0)
    remote_events = remote.get("events") or []
    for item in remote_events[synced_events:]:
        _event(db, job, item.get("type", "progress"), item.get("message", "采集进度更新"), item.get("payload") or {})
    scope["synced_event_count"] = len(remote_events)
    job.source_scope = scope

    existing_ids = {
        row[0] for row in db.query(CrawlEvidenceItem.external_item_id).filter(CrawlEvidenceItem.crawl_job_id == job.id).all()
    }
    for item in remote.get("items") or []:
        if item.get("item_id") in existing_ids:
            continue
        db.add(CrawlEvidenceItem(
            tenant_id=job.tenant_id,
            crawl_job_id=job.id,
            external_item_id=item.get("item_id"),
            source_type=item.get("source_type", "official"),
            source_site=item.get("source_site"),
            source_domain=item.get("source_domain"),
            source_url=item.get("source_url", ""),
            target_name=item.get("target_name"),
            field_name=item.get("field_name", "unknown"),
            field_value=item.get("field_value"),
            evidence_text=item.get("evidence_text", "")[:4000],
            content_hash=item.get("content_hash", ""),
            confidence=float(item.get("confidence") or 0.5),
            status="pending",
            collected_at=_parse_datetime(item.get("collected_at")),
        ))
    if previous_status != job.status:
        _event(db, job, "status_changed", f"采集状态：{previous_status} -> {job.status}")
    db.commit()
    db.refresh(job)
    return job


async def cancel_external_job(db: Session, job: CrawlJob) -> CrawlJob:
    cfg = crawler_settings(db)
    if job.external_job_id and job.status not in TERMINAL_STATUSES:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{cfg['service_url']}/v1/jobs/{job.external_job_id}/cancel",
                    headers={"Authorization": f"Bearer {cfg['token']}"},
                )
                response.raise_for_status()
            job.status = response.json().get("status", "cancelling")
        except Exception as exc:
            raise RuntimeError(f"CRAWLER_CANCEL_FAILED: {exc}") from exc
    _event(db, job, "cancel_requested", "用户请求取消采集任务")
    db.commit()
    return job


def apply_confirmed_items(db: Session, job: CrawlJob, items: list[CrawlEvidenceItem], user_id: int) -> dict:
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == job.evaluation_id,
        EvaluationRecord.tenant_id == job.tenant_id,
    ).first()
    if not record:
        raise ValueError("EVALUATION_NOT_FOUND")
    manual = dict(record.manual_data or {})
    competitors = [dict(row) for row in (manual.get("competitors") or []) if isinstance(row, dict)]
    property_conditions = dict(manual.get("property_conditions") or {})
    property_listings = [dict(row) for row in (manual.get("property_listings") or []) if isinstance(row, dict)]
    policy_notes = [str(manual.get("policy_notes") or "").strip()] if manual.get("policy_notes") else []
    policy_sources = [dict(row) for row in (manual.get("policy_sources") or []) if isinstance(row, dict)]

    grouped: dict[tuple[str, str], list[CrawlEvidenceItem]] = {}
    for item in items:
        grouped.setdefault((item.source_type, item.target_name or "公开信息"), []).append(item)
    for (source_type, target), group in grouped.items():
        if source_type == "official":
            incoming = {}
            for item in group:
                value = item.reviewed_value if item.reviewed_value is not None else item.field_value
                incoming[item.field_name] = value
            competitors, row = merge_competitor_rows(
                competitors,
                target,
                incoming,
                {"source_site": group[0].source_site or "official"},
            )
            row.setdefault("source_url", group[0].source_url)
            row.setdefault("evidence", group[0].evidence_text)
            profile = db.query(CompetitorProfile).filter(
                CompetitorProfile.tenant_id == job.tenant_id,
                CompetitorProfile.name == target,
            ).first()
            if not profile:
                profile = CompetitorProfile(tenant_id=job.tenant_id, name=target, data_source="public", confidence=max(i.confidence or 0 for i in group), created_by=user_id)
                db.add(profile)
                db.flush()
            field_map = {"configuration": "configuration", "machine_count": "machine_count", "area_sqm": "area_sqm", "hourly_price": "hourly_price", "package_price": "package_price", "recharge_info": "recharge_info"}
            for item in group:
                attr = field_map.get(item.field_name)
                value = item.reviewed_value if item.reviewed_value is not None else item.field_value
                if attr and getattr(profile, attr) in (None, ""):
                    setattr(profile, attr, value)
            db.add(CompetitorObservation(
                tenant_id=job.tenant_id,
                competitor_id=profile.id,
                hourly_price=profile.hourly_price,
                package_price=profile.package_price,
                recharge_info=profile.recharge_info,
                activity_note="；".join(i.evidence_text[:180] for i in group[:3]),
                observer="public-crawl-confirmed",
                data_source="public",
                created_by=user_id,
            ))
        elif source_type == "property":
            listing = {"name": target, "source_url": group[0].source_url, "source_site": group[0].source_site, "status": "public_confirmed"}
            for item in group:
                value = item.reviewed_value if item.reviewed_value is not None else item.field_value
                listing[item.field_name] = value
            property_conditions = merge_property_conditions(property_conditions, listing)
            if not any(row.get("source_url") == listing["source_url"] for row in property_listings):
                property_listings.append(listing)
            property_conditions.setdefault("source_url", group[0].source_url)
            property_conditions.setdefault("evidence", group[0].evidence_text)
        elif source_type == "government":
            for item in group:
                value = item.reviewed_value if item.reviewed_value is not None else item.field_value
                if item.field_name == "policy_note":
                    policy_notes.append(f"{value}（来源：{item.source_url}）")
            policy_source = {"title": target, "source_url": group[0].source_url, "source_site": group[0].source_site or "gov"}
            for item in group:
                value = item.reviewed_value if item.reviewed_value is not None else item.field_value
                if item.field_name in {"document_number", "published_at", "issuing_authority"}:
                    policy_source[item.field_name] = value
            if not any(row.get("source_url") == policy_source["source_url"] for row in policy_sources):
                policy_sources.append(policy_source)

    manual["competitors"] = competitors
    manual["property_conditions"] = property_conditions
    manual["property_listings"] = property_listings
    manual["policy_notes"] = "\n".join(filter(None, policy_notes))[:6000]
    manual["policy_sources"] = policy_sources
    record.manual_data = manual
    db.commit()
    return manual


async def regenerate_after_confirmation(job_id: int, user_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if not job:
            return
        original = db.query(EvaluationRecord).filter(EvaluationRecord.id == job.evaluation_id).first()
        if not original:
            raise ValueError("EVALUATION_NOT_FOUND")
        final_result = None
        async for step in evaluate_location(
            address=original.address,
            city=None,
            db=db,
            tenant_id=job.tenant_id,
            radius=original.radius or 1500,
            allow_mock_data=False,
            manual_data=original.manual_data or {},
            created_by=user_id,
        ):
            if step.get("type") == "final":
                final_result = step
        if not final_result or not final_result.get("evaluation_id"):
            raise RuntimeError("REGENERATED_EVALUATION_MISSING")
        job.regenerated_evaluation_id = final_result["evaluation_id"]
        regenerated = db.query(EvaluationRecord).filter(EvaluationRecord.id == final_result["evaluation_id"]).first()
        if regenerated:
            regenerated.source_type = "public_crawl_confirmed"
        job.status = "regenerated"
        job.progress = 100
        job.finished_at = datetime.utcnow()
        _event(db, job, "regenerated", f"已生成新版评估 {job.regenerated_evaluation_id}")
        db.commit()
    except Exception as exc:
        logger.exception("确认采集证据后重新评估失败，job_id=%s", job_id)
        db.rollback()
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if job:
            job.status = "regeneration_failed"
            job.error_message = f"REGENERATION_FAILED: {str(exc)[:300]}"
            _event(db, job, "regeneration_failed", "采集结果已确认，但重新生成报告失败", {"error": str(exc)[:200]})
            db.commit()
    finally:
        db.close()
