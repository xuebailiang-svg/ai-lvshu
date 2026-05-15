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
import logging
import urllib.parse
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_active_user
from app.models.user import User
from app.models.store import Store, UploadRecord, KnowledgeDocument, DocumentInsight, ScoringRule
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


# ─── 评分权重查询 ─────────────────────────────────────────────────────────────

@router.get("/scoring-rules", summary="获取当前评分权重")
def get_scoring_rules(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    tenant_id = current_user.tenant_id or 1
    rules = db.query(ScoringRule).filter(
        ScoringRule.tenant_id == tenant_id,
        ScoringRule.is_active == True
    ).all()

    return [
        {
            "dimension": r.dimension,
            "dimension_name": r.dimension_name,
            "sub_factor": r.sub_factor,
            "base_weight": r.base_weight,
            "dynamic_weight": r.dynamic_weight,
            "effective_weight": r.effective_weight,
            "last_updated_by": r.last_updated_by,
            "update_reason": r.update_reason,
            "update_count": r.update_count,
        }
        for r in rules
    ]


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
