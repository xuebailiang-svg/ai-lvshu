"""
数据管理 API
- 模板下载
- 文件上传（基础/营收/会员/硬件）
- 店铺列表与详情
- 上传记录查询
- 手动触发数据分析
- 异步地理编码
"""
import asyncio
import json
import logging
import os
import urllib.parse
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_active_user
from app.models.user import User
from app.models.store import (
    CompetitorObservation,
    CompetitorProfile,
    ExcludedKnowledgeSource,
    HardwareConfig,
    KnowledgeDocument,
    DocumentInsight,
    MemberProfile,
    RevenueRecord,
    ScoringModelVersion,
    ScoringRule,
    Store,
    UploadRecord,
)
from app.services.importer import process_upload
from app.services.document_importer import (
    process_document_upload,
    approve_document_insight,
    reject_document_insight,
    ALLOWED_DOCUMENT_EXTENSIONS,
)
from app.services.analyzer import run_full_analysis
from app.services.template_generator import TEMPLATE_GENERATORS, TEMPLATE_NAMES
from app.services.amap import geocode_address, get_amap_key

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_UPLOAD_TYPES = ["basic", "revenue", "member", "hardware"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class DocumentInsightReviewRequest(BaseModel):
    note: str = ""


class CompetitorProfileRequest(BaseModel):
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    machine_count: Optional[int] = None
    area_sqm: Optional[float] = None
    hourly_price: Optional[float] = None
    package_price: Optional[float] = None
    occupancy_rate: Optional[float] = None
    open_years: Optional[float] = None
    monthly_sales: Optional[float] = None
    annual_sales: Optional[float] = None
    recharge_info: Optional[str] = None
    configuration: Optional[str] = None
    notes: Optional[str] = None
    data_source: str = "manual"
    confidence: float = 0.7


class CompetitorObservationRequest(BaseModel):
    observed_at: Optional[datetime] = None
    occupancy_rate: Optional[float] = None
    hourly_price: Optional[float] = None
    package_price: Optional[float] = None
    recharge_info: Optional[str] = None
    activity_note: Optional[str] = None
    observer: Optional[str] = None
    data_source: str = "manual"


def _competitor_to_dict(item: CompetitorProfile, include_observations: bool = False) -> dict:
    payload = {
        "id": item.id,
        "name": item.name,
        "address": item.address,
        "city": item.city,
        "district": item.district,
        "longitude": item.longitude,
        "latitude": item.latitude,
        "machine_count": item.machine_count,
        "area_sqm": item.area_sqm,
        "hourly_price": item.hourly_price,
        "package_price": item.package_price,
        "occupancy_rate": item.occupancy_rate,
        "open_years": item.open_years,
        "monthly_sales": item.monthly_sales,
        "annual_sales": item.annual_sales,
        "recharge_info": item.recharge_info,
        "configuration": item.configuration,
        "notes": item.notes,
        "data_source": item.data_source,
        "confidence": item.confidence,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if include_observations:
        payload["observations"] = [
            {
                "id": obs.id,
                "observed_at": obs.observed_at,
                "occupancy_rate": obs.occupancy_rate,
                "hourly_price": obs.hourly_price,
                "package_price": obs.package_price,
                "recharge_info": obs.recharge_info,
                "activity_note": obs.activity_note,
                "observer": obs.observer,
                "data_source": obs.data_source,
                "created_at": obs.created_at,
            }
            for obs in sorted(item.observations, key=lambda row: row.observed_at or row.created_at, reverse=True)
        ]
    return payload


# ─── 模板下载 ────────────────────────────────────────────────────────────────

@router.get("/templates/{template_type}", summary="下载上传模板")
def download_template(template_type: str, _: User = Depends(get_current_active_user)):
    """
    下载标准 Excel 上传模板
    template_type: basic | revenue | member | hardware
    """
    if template_type not in TEMPLATE_GENERATORS:
        raise HTTPException(status_code=404, detail=f"模板类型 '{template_type}' 不存在")

    file_bytes = TEMPLATE_GENERATORS[template_type]()
    cn_name = TEMPLATE_NAMES[template_type]
    # RFC 5987 编码：对中文文件名进行 URL 编码，避免 latin-1 编码错误
    encoded_name = urllib.parse.quote(f"{cn_name}.xlsx", safe='')
    ascii_name = f"template_{template_type}.xlsx"  # ASCII 兜底文件名

    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"
        }
    )


@router.get("/templates", summary="获取所有模板列表")
def list_templates(_: User = Depends(get_current_active_user)):
    """返回所有可用模板信息"""
    return [
        {
            "type": t,
            "name": TEMPLATE_NAMES[t],
            "download_url": f"/api/v1/data/templates/{t}",
            "description": _template_descriptions[t]
        }
        for t in TEMPLATE_GENERATORS
    ]

_template_descriptions = {
    "basic": "店铺基础信息（名称、地址、面积、机器数等），是其他模板的前置依赖",
    "revenue": "月度/年度营收数据（各类收入、成本、净利润、客流量）",
    "member": "会员画像数据（年龄分布、性别、职业、消费行为及营收贡献）",
    "hardware": "硬件配置数据（显卡型号分布、座位分类、外设品牌、带宽）",
}


# ─── 文件上传 ────────────────────────────────────────────────────────────────

@router.post("/upload", summary="上传历史数据文件")
async def upload_data(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    upload_type: str = Form(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    上传历史运营数据 Excel 文件
    流程: 保存原始文件 → 解析入库 → 后台触发分析 → 更新评分权重
    """
    if upload_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的上传类型，可选: {ALLOWED_UPLOAD_TYPES}")

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 Excel 文件（.xlsx 或 .xls）")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 10MB 限制")

    tenant_id = current_user.tenant_id or 1

    # 同步处理：保存文件 + 解析入库
    try:
        upload_record = process_upload(
            file_bytes=file_bytes,
            filename=file.filename,
            upload_type=upload_type,
            tenant_id=tenant_id,
            user_id=current_user.id,
            db=db
        )
    except Exception as e:
        logger.exception("历史数据上传处理失败")
        raise HTTPException(status_code=500, detail=f"上传处理失败：{e}") from e

    # 后台异步：地理编码 + 数据分析 + 权重更新
    if upload_record.parse_status == "success":
        background_tasks.add_task(
            _background_post_process,
            upload_record_id=upload_record.id,
            tenant_id=tenant_id,
            upload_type=upload_type
        )

    return {
        "upload_id": upload_record.id,
        "filename": upload_record.original_filename,
        "parse_status": upload_record.parse_status,
        "parsed_rows": upload_record.parsed_rows,
        "failed_rows": upload_record.failed_rows,
        "message": upload_record.parse_message,
        "analysis_status": "processing（后台进行中）" if upload_record.parse_status == "success" else "skipped（解析失败，未启动后台分析）"
    }


async def _background_post_process(upload_record_id: int, tenant_id: int, upload_type: str):
    """后台任务：地理编码 + 数据分析"""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        # 1. 对 pending 状态的店铺进行地理编码
        amap_key = get_amap_key(db)
        if amap_key:
            pending_stores = db.query(Store).filter(
                Store.tenant_id == tenant_id,
                Store.geo_status == "pending"
            ).all()
            for store in pending_stores:
                result = await geocode_address(store.address, store.city, amap_key)
                if result:
                    store.longitude, store.latitude = result
                    store.geo_status = "success"
                    logger.info(f"店铺 '{store.name}' 地理编码成功: {result}")
                else:
                    store.geo_status = "failed"
                    logger.warning(f"店铺 '{store.name}' 地理编码失败")
            db.commit()

        # 2. 触发数据分析（仅在有足够数据时）
        store_count = db.query(Store).filter(Store.tenant_id == tenant_id).count()
        if store_count >= 1:
            run_full_analysis(db, tenant_id, upload_record_id)
            logger.info(f"数据分析完成，租户 {tenant_id}")

    except Exception as e:
        logger.error(f"后台处理失败: {e}")
        db.rollback()
    finally:
        db.close()


# ─── 经验文档上传与审核 ─────────────────────────────────────────────────────────────

@router.post("/documents/upload", summary="上传经验文档或调研报告")
async def upload_knowledge_document(
    file: UploadFile = File(...),
    scope_type: str = Form("brand"),
    store_id: Optional[int] = Form(None),
    candidate_address: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择要上传的文档")
    if not any(file.filename.lower().endswith(ext) for ext in ALLOWED_DOCUMENT_EXTENSIONS):
        raise HTTPException(status_code=400, detail="仅支持 .txt / .docx / .pdf 经验文档")

    file_bytes = await file.read()
    tenant_id = current_user.tenant_id or 1
    try:
        document = await process_document_upload(
            file_bytes=file_bytes,
            filename=file.filename,
            scope_type=scope_type,
            tenant_id=tenant_id,
            user_id=current_user.id,
            db=db,
            store_id=store_id,
            candidate_address=candidate_address,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("经验文档上传处理失败")
        raise HTTPException(status_code=500, detail=f"经验文档上传处理失败：{e}") from e

    return _document_payload(document, include_detail=True)


@router.get("/documents", summary="获取经验文档列表")
def list_knowledge_documents(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    query = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant_id)
    total = query.count()
    documents = query.order_by(KnowledgeDocument.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_document_payload(doc, include_detail=False) for doc in documents],
    }


@router.get("/documents/{document_id}", summary="获取经验文档详情")
def get_knowledge_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == document_id,
        KnowledgeDocument.tenant_id == tenant_id,
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="经验文档不存在")
    return _document_payload(document, include_detail=True)


@router.delete("/documents/{document_id}", summary="删除经验文档")
def delete_knowledge_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == document_id,
        KnowledgeDocument.tenant_id == tenant_id,
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="经验文档不存在")

    stored_path = document.stored_path
    try:
        db.execute(text("""
            DELETE FROM knowledge_vectors
            WHERE tenant_id = :tenant_id
              AND source_type = 'document_experience'
              AND metadata->>'document_id' = :document_id
        """), {"tenant_id": tenant_id, "document_id": str(document_id)})
    except Exception as e:
        logger.warning(f"删除文档向量失败，继续删除文档记录: {e}")
        db.rollback()

    db.delete(document)
    db.commit()
    _safe_remove_file(stored_path)
    return {"message": "经验文档已删除"}


@router.post("/document-insights/{insight_id}/approve", summary="确认经验文档权重建议")
def approve_insight(
    insight_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    insight = _get_tenant_insight(insight_id, current_user.tenant_id or 1, db)
    if insight.status == "approved":
        raise HTTPException(status_code=400, detail="该建议已确认生效")
    if insight.status == "rejected":
        raise HTTPException(status_code=400, detail="该建议已被忽略，不能再次确认")
    try:
        rule = approve_document_insight(insight, current_user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "message": "建议已确认，评分权重已更新",
        "insight": _insight_payload(insight),
        "rule": {
            "dimension": rule.dimension,
            "sub_factor": rule.sub_factor,
            "dynamic_weight": rule.dynamic_weight,
            "effective_weight": rule.effective_weight,
            "update_reason": rule.update_reason,
        },
    }


@router.post("/document-insights/{insight_id}/reject", summary="忽略经验文档权重建议")
def reject_insight(
    insight_id: int,
    req: Optional[DocumentInsightReviewRequest] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    insight = _get_tenant_insight(insight_id, current_user.tenant_id or 1, db)
    if insight.status == "approved":
        raise HTTPException(status_code=400, detail="该建议已确认生效，不能忽略")
    reject_document_insight(insight, current_user.id, db, req.note if req else "")
    return {"message": "建议已忽略", "insight": _insight_payload(insight)}


def _get_tenant_insight(insight_id: int, tenant_id: int, db: Session) -> DocumentInsight:
    insight = db.query(DocumentInsight).filter(
        DocumentInsight.id == insight_id,
        DocumentInsight.tenant_id == tenant_id,
    ).first()
    if not insight:
        raise HTTPException(status_code=404, detail="文档建议不存在")
    return insight


def _document_payload(document: KnowledgeDocument, include_detail: bool = False) -> dict:
    insights = document.insights or []
    payload = {
        "id": document.id,
        "filename": document.original_filename,
        "file_type": document.file_type,
        "file_size": document.file_size,
        "scope_type": document.scope_type,
        "store_id": document.store_id,
        "store_name": document.store.name if document.store else None,
        "candidate_address": document.candidate_address,
        "parse_status": document.parse_status,
        "parse_message": document.parse_message,
        "vector_status": document.vector_status,
        "vector_message": document.vector_message,
        "chunk_count": document.chunk_count,
        "summary": document.summary,
        "insight_count": len(insights),
        "pending_insight_count": len([i for i in insights if i.status == "pending"]),
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }
    if include_detail:
        payload["chunks"] = document.chunks or []
        payload["insights"] = [_insight_payload(i) for i in insights]
    return payload


def _insight_payload(insight: DocumentInsight) -> dict:
    return {
        "id": insight.id,
        "document_id": insight.document_id,
        "dimension": insight.dimension,
        "dimension_name": insight.dimension_name,
        "sub_factor": insight.sub_factor,
        "insight": insight.insight,
        "evidence": insight.evidence,
        "adjustment_direction": insight.adjustment_direction,
        "suggested_weight": insight.suggested_weight,
        "confidence": insight.confidence,
        "status": insight.status,
        "review_note": insight.review_note,
        "reviewed_at": insight.reviewed_at.isoformat() if insight.reviewed_at else None,
        "created_at": insight.created_at.isoformat() if insight.created_at else None,
    }


def _safe_remove_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        logger.warning(f"删除本地文件失败: {path}, {e}")


# ─── 上传记录查询 ─────────────────────────────────────────────────────────────

@router.get("/uploads", summary="获取上传记录列表")
def list_uploads(
    page: int = 1,
    page_size: int = 20,
    upload_type: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    query = db.query(UploadRecord).filter(UploadRecord.tenant_id == tenant_id)
    if upload_type:
        query = query.filter(UploadRecord.upload_type == upload_type)
    total = query.count()
    records = query.order_by(UploadRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "filename": r.original_filename,
                "upload_type": r.upload_type,
                "parse_status": r.parse_status,
                "analysis_status": r.analysis_status,
                "parsed_rows": r.parsed_rows,
                "failed_rows": r.failed_rows,
                "weight_updated": r.weight_updated,
                "analysis_summary": r.analysis_summary,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    }


@router.get("/uploads/{upload_id}", summary="获取上传记录详情")
def get_upload_detail(
    upload_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(UploadRecord).filter(
        UploadRecord.id == upload_id,
        UploadRecord.tenant_id == tenant_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="上传记录不存在")

    return {
        "id": record.id,
        "filename": record.original_filename,
        "upload_type": record.upload_type,
        "file_size": record.file_size,
        "parse_status": record.parse_status,
        "parse_message": record.parse_message,
        "parsed_rows": record.parsed_rows,
        "failed_rows": record.failed_rows,
        "parse_detail": record.parse_detail,
        "analysis_status": record.analysis_status,
        "analysis_summary": record.analysis_summary,
        "weight_updated": record.weight_updated,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.delete("/uploads/{upload_id}", summary="删除上传记录")
def delete_upload_record(
    upload_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(UploadRecord).filter(
        UploadRecord.id == upload_id,
        UploadRecord.tenant_id == tenant_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="上传记录不存在")

    stored_path = record.stored_path
    deleted_rows = {
        "revenue": db.query(RevenueRecord).filter(
            RevenueRecord.tenant_id == tenant_id,
            RevenueRecord.upload_record_id == upload_id,
        ).delete(synchronize_session=False),
        "member": db.query(MemberProfile).filter(
            MemberProfile.tenant_id == tenant_id,
            MemberProfile.upload_record_id == upload_id,
        ).delete(synchronize_session=False),
        "hardware": db.query(HardwareConfig).filter(
            HardwareConfig.tenant_id == tenant_id,
            HardwareConfig.upload_record_id == upload_id,
        ).delete(synchronize_session=False),
    }

    # 基础信息上传可能已被后续营收/会员/硬件数据引用，不自动删除门店本体。
    db.delete(record)
    db.commit()
    _safe_remove_file(stored_path)
    return {
        "message": "上传记录已删除",
        "deleted_rows": deleted_rows,
        "note": "基础信息上传删除只移除上传记录和原始文件，不自动删除门店本体。",
    }


# ─── 店铺管理 ─────────────────────────────────────────────────────────────────

@router.get("/stores", summary="获取店铺列表")
def list_stores(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    query = db.query(Store).filter(Store.tenant_id == tenant_id)
    if status:
        query = query.filter(Store.status == status)
    total = query.count()
    stores = query.order_by(Store.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "address": s.address,
                "city": s.city,
                "longitude": s.longitude,
                "latitude": s.latitude,
                "geo_status": s.geo_status,
                "area_sqm": s.area_sqm,
                "machine_count": s.machine_count,
                "status": s.status,
                "is_success": s.is_success,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in stores
        ]
    }


@router.get("/stores/{store_id}", summary="获取店铺详情")
def get_store_detail(
    store_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    store = db.query(Store).filter(
        Store.id == store_id,
        Store.tenant_id == tenant_id
    ).first()
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")

    return {
        "id": store.id,
        "name": store.name,
        "address": store.address,
        "city": store.city,
        "district": store.district,
        "longitude": store.longitude,
        "latitude": store.latitude,
        "geo_status": store.geo_status,
        "area_sqm": store.area_sqm,
        "machine_count": store.machine_count,
        "monthly_rent": store.monthly_rent,
        "status": store.status,
        "is_success": store.is_success,
        "experience_notes": store.experience_notes,
        "open_date": store.open_date.isoformat() if store.open_date else None,
        "revenue_count": len(store.revenue_records),
        "member_profile_count": len(store.member_profiles),
    }


@router.delete("/stores/{store_id}", summary="删除店铺及其历史数据")
def delete_store(
    store_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    store = db.query(Store).filter(
        Store.id == store_id,
        Store.tenant_id == tenant_id
    ).first()
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")

    store_name = store.name
    deleted_rows = {
        "revenue": db.query(RevenueRecord).filter(
            RevenueRecord.tenant_id == tenant_id,
            RevenueRecord.store_id == store_id,
        ).count(),
        "member": db.query(MemberProfile).filter(
            MemberProfile.tenant_id == tenant_id,
            MemberProfile.store_id == store_id,
        ).count(),
        "hardware": db.query(HardwareConfig).filter(
            HardwareConfig.tenant_id == tenant_id,
            HardwareConfig.store_id == store_id,
        ).count(),
    }

    try:
        db.execute(text("""
            DELETE FROM knowledge_vectors
            WHERE tenant_id = :tenant_id
              AND source_type = 'store_experience'
              AND source_id = :store_id
        """), {"tenant_id": tenant_id, "store_id": store_id})
    except Exception as e:
        logger.warning(f"删除门店经验向量失败，继续删除店铺: {e}")
        db.rollback()
        store = db.query(Store).filter(Store.id == store_id, Store.tenant_id == tenant_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="店铺不存在")

    db.query(UploadRecord).filter(
        UploadRecord.tenant_id == tenant_id,
        UploadRecord.store_id == store_id,
    ).update({"store_id": None}, synchronize_session=False)
    db.query(KnowledgeDocument).filter(
        KnowledgeDocument.tenant_id == tenant_id,
        KnowledgeDocument.store_id == store_id,
    ).update({"store_id": None, "scope_type": "brand"}, synchronize_session=False)

    db.query(ExcludedKnowledgeSource).filter(
        ExcludedKnowledgeSource.tenant_id == tenant_id,
        ExcludedKnowledgeSource.source_type == "store_experience",
        ExcludedKnowledgeSource.source_id == store_id,
    ).delete(synchronize_session=False)

    db.delete(store)
    db.commit()
    return {
        "message": f"店铺「{store_name}」已删除",
        "deleted_rows": deleted_rows,
        "note": "已同步删除该店铺的营收、会员、硬件明细和门店经验知识库向量。",
    }


# ─── 知识库向量管理 ─────────────────────────────────────────────────────────────

def _source_type_label(source_type: str) -> str:
    labels = {
        "store_experience": "历史门店经验",
        "document_experience": "经验文档",
        "evaluation_result": "评估案例",
        "analysis_insight": "历史分析结论",
    }
    return labels.get(source_type, source_type)


@router.get("/knowledge-vectors", summary="查看知识库内容")
def list_knowledge_vectors(
    page: int = 1,
    page_size: int = 20,
    source_type: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    params = {"tenant_id": tenant_id, "limit": page_size, "offset": (page - 1) * page_size}
    type_filter = ""
    if source_type:
        type_filter = "AND source_type = :source_type"
        params["source_type"] = source_type
    try:
        total = db.execute(text(f"""
            SELECT COUNT(*)
            FROM knowledge_vectors
            WHERE tenant_id = :tenant_id {type_filter}
        """), params).scalar() or 0
        rows = db.execute(text(f"""
            SELECT id, source_type, source_id, content, metadata, created_at, updated_at
            FROM knowledge_vectors
            WHERE tenant_id = :tenant_id {type_filter}
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()
    except Exception as e:
        logger.warning(f"读取知识库失败: {e}")
        return {
            "total": 0,
            "page": page,
            "page_size": page_size,
            "items": [],
            "warning": "知识库表不存在或 pgvector 未启用，暂无可展示内容。",
        }

    items = []
    for row in rows:
        metadata = row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}")
        source_name = (
            metadata.get("filename")
            or metadata.get("store_name")
            or metadata.get("address")
            or metadata.get("type")
            or _source_type_label(row[1])
        )
        items.append({
            "id": row[0],
            "source_type": row[1],
            "source_type_label": _source_type_label(row[1]),
            "source_id": row[2],
            "source_name": source_name,
            "content": row[3],
            "content_preview": (row[3] or "")[:220],
            "metadata": metadata,
            "created_at": row[5].isoformat() if row[5] else None,
            "updated_at": row[6].isoformat() if row[6] else None,
        })
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.delete("/knowledge-vectors/{vector_id}", summary="删除知识库内容")
def delete_knowledge_vector(
    vector_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    try:
        row = db.execute(text("""
            DELETE FROM knowledge_vectors
            WHERE id = :vector_id AND tenant_id = :tenant_id
            RETURNING id, source_type, source_id
        """), {"vector_id": vector_id, "tenant_id": tenant_id}).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(status_code=404, detail="知识库内容不存在")
        db.query(ExcludedKnowledgeSource).filter(
            ExcludedKnowledgeSource.tenant_id == tenant_id,
            ExcludedKnowledgeSource.source_type == row[1],
            ExcludedKnowledgeSource.source_id == row[2],
        ).delete(synchronize_session=False)
        db.commit()
        return {"message": "知识库内容已删除", "id": row[0]}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.warning(f"删除知识库内容失败: {e}")
        raise HTTPException(status_code=500, detail="知识库删除失败，可能是向量表未初始化") from e


# ─── 竞品档案 ───────────────────────────────────────────────────────────────

@router.get("/competitors", summary="获取竞品档案列表")
def list_competitors(
    keyword: Optional[str] = None,
    city: Optional[str] = None,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    query = db.query(CompetitorProfile).filter(CompetitorProfile.tenant_id == tenant_id)
    if not include_inactive:
        query = query.filter(CompetitorProfile.is_active == True)
    if keyword:
        query = query.filter(CompetitorProfile.name.ilike(f"%{keyword.strip()}%"))
    if city:
        query = query.filter(CompetitorProfile.city == city.strip())
    items = query.order_by(CompetitorProfile.updated_at.desc()).limit(500).all()
    return {"items": [_competitor_to_dict(item) for item in items]}


@router.get("/competitors/{competitor_id}", summary="获取竞品档案详情")
def get_competitor(
    competitor_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    item = db.query(CompetitorProfile).filter(
        CompetitorProfile.id == competitor_id,
        CompetitorProfile.tenant_id == tenant_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="竞品档案不存在")
    return _competitor_to_dict(item, include_observations=True)


async def _fill_competitor_location(req: CompetitorProfileRequest, db: Session) -> tuple[Optional[float], Optional[float]]:
    if req.longitude is not None and req.latitude is not None:
        return req.longitude, req.latitude
    if not req.address:
        return req.longitude, req.latitude
    amap_key = get_amap_key(db)
    if not amap_key:
        return req.longitude, req.latitude
    try:
        result = await geocode_address(req.address, req.city, amap_key)
        if result:
            return result
    except Exception as e:
        logger.warning(f"竞品地址地理编码失败，不影响保存: {e}")
    return req.longitude, req.latitude


@router.post("/competitors", summary="新增竞品档案")
async def create_competitor(
    req: CompetitorProfileRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="竞品名称不能为空")
    longitude, latitude = await _fill_competitor_location(req, db)
    item = CompetitorProfile(
        tenant_id=tenant_id,
        name=name,
        address=req.address,
        city=req.city,
        district=req.district,
        longitude=longitude,
        latitude=latitude,
        machine_count=req.machine_count,
        area_sqm=req.area_sqm,
        hourly_price=req.hourly_price,
        package_price=req.package_price,
        occupancy_rate=req.occupancy_rate,
        open_years=req.open_years,
        monthly_sales=req.monthly_sales,
        annual_sales=req.annual_sales,
        recharge_info=req.recharge_info,
        configuration=req.configuration,
        notes=req.notes,
        data_source=req.data_source,
        confidence=req.confidence,
        created_by=current_user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"message": "竞品档案已新增", "item": _competitor_to_dict(item)}


@router.put("/competitors/{competitor_id}", summary="更新竞品档案")
async def update_competitor(
    competitor_id: int,
    req: CompetitorProfileRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    item = db.query(CompetitorProfile).filter(
        CompetitorProfile.id == competitor_id,
        CompetitorProfile.tenant_id == tenant_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="竞品档案不存在")
    longitude, latitude = await _fill_competitor_location(req, db)
    for field, value in {
        "name": req.name.strip(),
        "address": req.address,
        "city": req.city,
        "district": req.district,
        "longitude": longitude,
        "latitude": latitude,
        "machine_count": req.machine_count,
        "area_sqm": req.area_sqm,
        "hourly_price": req.hourly_price,
        "package_price": req.package_price,
        "occupancy_rate": req.occupancy_rate,
        "open_years": req.open_years,
        "monthly_sales": req.monthly_sales,
        "annual_sales": req.annual_sales,
        "recharge_info": req.recharge_info,
        "configuration": req.configuration,
        "notes": req.notes,
        "data_source": req.data_source,
        "confidence": req.confidence,
    }.items():
        setattr(item, field, value)
    db.commit()
    return {"message": "竞品档案已更新", "item": _competitor_to_dict(item)}


@router.delete("/competitors/{competitor_id}", summary="停用竞品档案")
def delete_competitor(
    competitor_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    item = db.query(CompetitorProfile).filter(
        CompetitorProfile.id == competitor_id,
        CompetitorProfile.tenant_id == tenant_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="竞品档案不存在")
    item.is_active = False
    db.commit()
    return {"message": "竞品档案已停用", "id": item.id}


@router.post("/competitors/{competitor_id}/observations", summary="新增竞品观察记录")
def create_competitor_observation(
    competitor_id: int,
    req: CompetitorObservationRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    item = db.query(CompetitorProfile).filter(
        CompetitorProfile.id == competitor_id,
        CompetitorProfile.tenant_id == tenant_id,
        CompetitorProfile.is_active == True,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="竞品档案不存在")
    obs = CompetitorObservation(
        tenant_id=tenant_id,
        competitor_id=item.id,
        observed_at=req.observed_at or datetime.utcnow(),
        occupancy_rate=req.occupancy_rate,
        hourly_price=req.hourly_price,
        package_price=req.package_price,
        recharge_info=req.recharge_info,
        activity_note=req.activity_note,
        observer=req.observer,
        data_source=req.data_source,
        created_by=current_user.id,
    )
    db.add(obs)
    if req.occupancy_rate is not None:
        item.occupancy_rate = req.occupancy_rate
    if req.hourly_price is not None:
        item.hourly_price = req.hourly_price
    if req.package_price is not None:
        item.package_price = req.package_price
    if req.recharge_info:
        item.recharge_info = req.recharge_info
    db.commit()
    return {"message": "竞品观察记录已新增", "competitor": _competitor_to_dict(item, include_observations=True)}


# ─── 评分权重查询 ─────────────────────────────────────────────────────────────

class ScoringRuleRequest(BaseModel):
    dimension: str
    dimension_name: str
    sub_factor: Optional[str] = None
    base_weight: float
    effective_weight: Optional[float] = None
    update_reason: Optional[str] = None


@router.get("/scoring-rules", summary="获取当前评分权重")
def get_scoring_rules(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    query = db.query(ScoringRule).filter(ScoringRule.tenant_id == tenant_id)
    if not include_inactive:
        query = query.filter(ScoringRule.is_active == True)
    rules = query.order_by(ScoringRule.dimension.asc(), ScoringRule.id.asc()).all()

    return [
        {
            "id": r.id,
            "dimension": r.dimension,
            "dimension_name": r.dimension_name,
            "sub_factor": r.sub_factor,
            "base_weight": r.base_weight,
            "dynamic_weight": r.dynamic_weight,
            "effective_weight": r.effective_weight,
            "last_updated_by": r.last_updated_by,
            "update_reason": r.update_reason,
            "update_count": r.update_count,
            "is_active": r.is_active,
        }
        for r in rules
    ]


def _validate_weight(value: float) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="权重必须是数字")
    if weight < 0 or weight > 1:
        raise HTTPException(status_code=400, detail="权重范围必须在 0 到 1 之间")
    return weight


def _ensure_unique_rule(db: Session, tenant_id: int, dimension: str, sub_factor: Optional[str], exclude_id: Optional[int] = None) -> None:
    query = db.query(ScoringRule).filter(
        ScoringRule.tenant_id == tenant_id,
        ScoringRule.dimension == dimension,
        ScoringRule.sub_factor == sub_factor,
        ScoringRule.is_active == True,
    )
    if exclude_id:
        query = query.filter(ScoringRule.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=400, detail="该大类下已存在相同小类")


def _invalidate_active_model_versions(db: Session, tenant_id: int) -> None:
    db.query(ScoringModelVersion).filter(
        ScoringModelVersion.tenant_id == tenant_id,
        ScoringModelVersion.is_active == True,
    ).update({ScoringModelVersion.is_active: False}, synchronize_session=False)


@router.post("/scoring-rules", summary="新增评分小类权重")
def create_scoring_rule(
    req: ScoringRuleRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    dimension = req.dimension.strip()
    sub_factor = (req.sub_factor or "").strip() or None
    if not dimension:
        raise HTTPException(status_code=400, detail="评分大类不能为空")
    _ensure_unique_rule(db, tenant_id, dimension, sub_factor)
    base_weight = _validate_weight(req.base_weight)
    effective_weight = _validate_weight(req.effective_weight if req.effective_weight is not None else base_weight)
    rule = ScoringRule(
        tenant_id=tenant_id,
        dimension=dimension,
        dimension_name=req.dimension_name.strip() or dimension,
        sub_factor=sub_factor,
        base_weight=base_weight,
        dynamic_weight=effective_weight,
        effective_weight=effective_weight,
        last_updated_by="manual",
        update_reason=req.update_reason or "用户手动新增评分小类",
        update_count=1,
        is_active=True,
    )
    db.add(rule)
    _invalidate_active_model_versions(db, tenant_id)
    db.commit()
    db.refresh(rule)
    return {"message": "评分小类已新增", "id": rule.id}


@router.put("/scoring-rules/{rule_id}", summary="修改评分小类权重")
def update_scoring_rule(
    rule_id: int,
    req: ScoringRuleRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    rule = db.query(ScoringRule).filter(ScoringRule.id == rule_id, ScoringRule.tenant_id == tenant_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="评分规则不存在")
    dimension = req.dimension.strip()
    sub_factor = (req.sub_factor or "").strip() or None
    _ensure_unique_rule(db, tenant_id, dimension, sub_factor, exclude_id=rule.id)
    base_weight = _validate_weight(req.base_weight)
    effective_weight = _validate_weight(req.effective_weight if req.effective_weight is not None else base_weight)
    rule.dimension = dimension
    rule.dimension_name = req.dimension_name.strip() or dimension
    rule.sub_factor = sub_factor
    rule.base_weight = base_weight
    rule.dynamic_weight = effective_weight
    rule.effective_weight = effective_weight
    rule.last_updated_by = "manual"
    rule.update_reason = req.update_reason or "用户手动调整评分权重"
    rule.update_count = (rule.update_count or 0) + 1
    rule.is_active = True
    _invalidate_active_model_versions(db, tenant_id)
    db.commit()
    return {"message": "评分权重已更新", "id": rule.id}


@router.delete("/scoring-rules/{rule_id}", summary="停用评分小类")
def delete_scoring_rule(
    rule_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    rule = db.query(ScoringRule).filter(ScoringRule.id == rule_id, ScoringRule.tenant_id == tenant_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="评分规则不存在")
    rule.is_active = False
    rule.last_updated_by = "manual"
    rule.update_reason = "用户手动停用评分小类"
    rule.update_count = (rule.update_count or 0) + 1
    _invalidate_active_model_versions(db, tenant_id)
    db.commit()
    return {"message": "评分小类已停用", "id": rule.id}


# ─── 手动触发分析 ─────────────────────────────────────────────────────────────

@router.post("/analyze/{upload_id}", summary="手动触发数据分析")
def trigger_analysis(
    upload_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(UploadRecord).filter(
        UploadRecord.id == upload_id,
        UploadRecord.tenant_id == tenant_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="上传记录不存在")

    result = run_full_analysis(db, tenant_id, upload_id)
    return {
        "message": "分析完成",
        "updated_weight_count": result["updated_weight_count"],
        "summary": result["summary"]
    }
