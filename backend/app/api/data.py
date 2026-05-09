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
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_active_user
from app.models.user import User
from app.models.store import Store, UploadRecord, ScoringRule
from app.services.importer import process_upload
from app.services.analyzer import run_full_analysis
from app.services.template_generator import TEMPLATE_GENERATORS, TEMPLATE_NAMES
from app.services.amap import geocode_address, get_amap_key

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_UPLOAD_TYPES = ["basic", "revenue", "member", "hardware"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


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
    filename = f"{TEMPLATE_NAMES[template_type]}.xlsx"

    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
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

    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 Excel 文件（.xlsx 或 .xls）")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 10MB 限制")

    tenant_id = current_user.tenant_id or 1

    # 同步处理：保存文件 + 解析入库
    upload_record = process_upload(
        file_bytes=file_bytes,
        filename=file.filename,
        upload_type=upload_type,
        tenant_id=tenant_id,
        user_id=current_user.id,
        db=db
    )

    # 后台异步：地理编码 + 数据分析 + 权重更新
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
        "analysis_status": "processing（后台进行中）"
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
