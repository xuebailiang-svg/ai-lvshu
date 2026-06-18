"""
单点评估 API
- POST /api/v1/evaluate/single  - 单点评估（SSE 流式输出）
- GET  /api/v1/evaluate/history - 历史评估记录
- GET  /api/v1/evaluate/stores  - 获取连锁门店坐标（用于地图标记）
"""
import json
import asyncio
import logging
from typing import Optional
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.db.session import SessionLocal
from app.models.user import User
from app.core.crypto import decrypt_config_value
from app.models.store import CompetitorProfile, EvaluationFeedback, EvaluationRecord, Store, ScoringRule, UploadRecord
from app.models.system_config import SystemConfig
from app.api.analysis import sync_feedback_and_quality_insights
from app.services.research_excel import build_research_workbook, parse_research_workbook
from app.services.scoring import build_research_required_fields, build_research_tables, evaluate_location

logger = logging.getLogger(__name__)
router = APIRouter(tags=["评估"])


class EvaluateRequest(BaseModel):
    address: str
    city: Optional[str] = None
    radius: int = 1500  # 评估半径（米）
    allow_mock_data: bool = False
    manual_data: Optional[dict] = None
    trigger_public_crawl: bool = True


class EvaluationFeedbackRequest(BaseModel):
    accurate_aspects: Optional[list[str]] = None
    inaccurate_aspects: Optional[list[str]] = None
    abnormal_data: Optional[list[dict]] = None
    actual_daily_customers: Optional[float] = None
    actual_monthly_revenue: Optional[float] = None
    actual_monthly_profit: Optional[float] = None
    actual_occupancy_rate: Optional[float] = None
    actual_member_growth: Optional[float] = None
    notes: str = ""


class ResearchDraftRequest(BaseModel):
    manual_data: dict = Field(default_factory=dict)


class ResearchImportConfirmRequest(BaseModel):
    manual_data: dict = Field(default_factory=dict)


@router.post("/single")
async def evaluate_single(
    req: EvaluateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    单点地址评估（SSE 流式输出，支持实时工作流可视化）
    前端通过 EventSource 接收实时日志
    """
    # 提前提取用户属性，避免 StreamingResponse 后 Session 已关闭导致 lazy load 失败
    tenant_id = current_user.tenant_id
    user_id = current_user.id
    address = req.address
    city = req.city
    radius = req.radius

    async def event_stream():
        # 使用独立的 db Session，不依赖外部已关闭的 db
        stream_db = SessionLocal()
        try:
            async for step in evaluate_location(
                address=address,
                city=city,
                db=stream_db,
                tenant_id=tenant_id,
                radius=radius,
                allow_mock_data=req.allow_mock_data,
                manual_data=req.manual_data or {},
                created_by=user_id,
            ):
                if step.get("type") == "final" and step.get("evaluation_id") and req.trigger_public_crawl:
                    from app.services.crawler import auto_start_crawl
                    asyncio.create_task(auto_start_crawl(step["evaluation_id"], tenant_id, user_id))
                data = json.dumps(step, ensure_ascii=False, default=str)
                yield f"data: {data}\n\n"
                await asyncio.sleep(0.02)  # 控制推送节奏

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"评估异常: {e}", exc_info=True)
            error_data = json.dumps({
                "type": "error",
                "step": "系统错误",
                "message": str(e)[:200],
                "data": {}
            }, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


@router.get("/data-readiness")
async def get_data_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """返回生成选址报告所需数据的就绪状态，供前端展示真实数据边界。"""
    tenant_id = current_user.tenant_id or 1
    config_keys = ["amap_api_key", "amap_huiyan_key", "llm.type", "llm.api_key", "llm.local_url", "llm.api_base", "llm.model_name"]
    configs = db.query(SystemConfig).filter(
        SystemConfig.config_key.in_(config_keys),
        SystemConfig.is_active == True
    ).all()
    cfg = {c.config_key: decrypt_config_value(c.config_value) for c in configs if c.config_value}
    upload_counts = {
        t: db.query(UploadRecord).filter(
            UploadRecord.tenant_id == tenant_id,
            UploadRecord.upload_type == t,
            UploadRecord.parse_status == "success"
        ).count()
        for t in ["basic", "revenue", "member", "hardware"]
    }
    competitor_count = db.query(CompetitorProfile).filter(
        CompetitorProfile.tenant_id == tenant_id,
        CompetitorProfile.is_active == True,
    ).count()

    llm_type = cfg.get("llm.type", "local")
    has_llm = bool(cfg.get("llm.model_name")) if llm_type == "local" else bool(cfg.get("llm.api_key"))
    items = [
        {
            "key": "amap_api_key",
            "name": "地址经纬度、周边 POI、交通、竞品、配套",
            "required": True,
            "ready": bool(cfg.get("amap_api_key")),
            "source": "系统配置：高德 Web 服务 API Key",
            "action": "到系统配置填写高德 API Key",
        },
        {
            "key": "rent_policy",
            "name": "候选地址租金、面积、政策/消防/证照限制",
            "required": True,
            "ready": False,
            "source": "客户针对每个候选地址补充",
            "action": "在本页点击“补充数据”填写",
        },
        {
            "key": "llm",
            "name": "AI 综合报告生成模型",
            "required": True,
            "ready": has_llm,
            "source": "系统配置：本地 Ollama 或云端模型 API",
            "action": "到系统配置填写模型地址或 API Key",
        },
        {
            "key": "basic",
            "name": "历史门店基础信息",
            "required": False,
            "ready": upload_counts["basic"] > 0,
            "count": upload_counts["basic"],
            "source": "数据管理上传",
            "action": "到数据管理上传基础信息模板",
        },
        {
            "key": "revenue",
            "name": "历史营收、成本、客流数据",
            "required": False,
            "ready": upload_counts["revenue"] > 0,
            "count": upload_counts["revenue"],
            "source": "数据管理上传",
            "action": "到数据管理上传营收数据模板",
        },
        {
            "key": "member",
            "name": "会员画像、年龄、职业、消费行为",
            "required": False,
            "ready": upload_counts["member"] > 0,
            "count": upload_counts["member"],
            "source": "数据管理上传",
            "action": "到数据管理上传会员画像模板",
        },
        {
            "key": "hardware",
            "name": "机器、座位、硬件配置",
            "required": False,
            "ready": upload_counts["hardware"] > 0,
            "count": upload_counts["hardware"],
            "source": "数据管理上传",
            "action": "到数据管理上传硬件配置模板",
        },
        {
            "key": "competitor_profiles",
            "name": "竞品档案、价格、配置、上座率、充值活动",
            "required": False,
            "ready": competitor_count > 0,
            "count": competitor_count,
            "source": "竞品档案 / 人工调研",
            "action": "到竞品档案录入已确认竞品数据",
        },
    ]
    return {
        "items": items,
        "upload_counts": upload_counts,
        "has_amap_key": bool(cfg.get("amap_api_key")),
        "has_huiyan_key": bool(cfg.get("amap_huiyan_key")),
        "has_llm": has_llm,
        "message": "真实报告必须使用已具备或客户补充的数据；模拟数据仅在用户明确授权后使用。",
    }


@router.get("/stores")
async def get_chain_stores(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取当前租户所有连锁门店坐标（用于地图标记）
    只返回已完成地理编码的店铺
    """
    stores = db.query(Store).filter(
        Store.tenant_id == current_user.tenant_id,
        Store.geo_status == "success",
        Store.longitude.isnot(None),
        Store.latitude.isnot(None)
    ).all()

    return {
        "total": len(stores),
        "stores": [
            {
                "id": s.id,
                "name": s.name,
                "address": s.address,
                "longitude": s.longitude,
                "latitude": s.latitude,
                "status": s.status,
                "is_success": s.is_success,
                "area_sqm": s.area_sqm,
                "machine_count": s.machine_count,
            }
            for s in stores
        ]
    }


@router.get("/scoring-rules")
async def get_scoring_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前评分规则（供前端雷达图展示维度权重）"""
    rules = db.query(ScoringRule).filter(
        ScoringRule.tenant_id == current_user.tenant_id,
        ScoringRule.is_active == True
    ).all()

    return [
        {
            "id": r.id,
            "dimension": r.dimension,
            "dimension_name": r.dimension_name,
            "sub_factor": r.sub_factor,
            "effective_weight": r.effective_weight,
            "last_updated_by": r.last_updated_by,
        }
        for r in rules
    ]


@router.get("/history")
async def list_evaluation_history(
    page: int = 1,
    page_size: int = 20,
    include_excluded: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    query = db.query(EvaluationRecord).filter(EvaluationRecord.tenant_id == tenant_id)
    if not include_excluded:
        query = query.filter(EvaluationRecord.is_excluded == False)
    total = query.count()
    records = query.order_by(EvaluationRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "items": [_evaluation_payload(record, include_detail=False) for record in records],
    }


@router.get("/history/{evaluation_id}")
async def get_evaluation_history_detail(
    evaluation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == tenant_id,
    ).first()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="评估记录不存在")
    return _evaluation_payload(record, include_detail=True)


@router.get("/{evaluation_id}/research")
async def get_evaluation_research(
    evaluation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == tenant_id,
    ).first()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="评估记录不存在")
    manual_data = record.manual_data or {}
    research_status = build_research_required_fields(manual_data)
    research_tables = build_research_tables(record.dimensions or {}, manual_data)
    return {
        "evaluation_id": record.id,
        "manual_data": manual_data,
        "research_required_fields": research_status["items"],
        "research_completion_rate": research_status["completion_rate"],
        "confirmed_poi_tables": research_tables["confirmed"],
        "excluded_poi_tables": research_tables["excluded"],
        "updated_at": record.updated_at.isoformat() if getattr(record, "updated_at", None) else None,
    }


@router.put("/{evaluation_id}/research")
async def update_evaluation_research(
    evaluation_id: int,
    req: ResearchDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == tenant_id,
    ).first()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="评估记录不存在")
    record.manual_data = req.manual_data or {}
    db.commit()
    db.refresh(record)
    research_status = build_research_required_fields(record.manual_data or {})
    research_tables = build_research_tables(record.dimensions or {}, record.manual_data or {})
    return {
        "message": "调研草稿已保存",
        "evaluation_id": record.id,
        "manual_data": record.manual_data or {},
        "research_required_fields": research_status["items"],
        "research_completion_rate": research_status["completion_rate"],
        "confirmed_poi_tables": research_tables["confirmed"],
        "excluded_poi_tables": research_tables["excluded"],
    }


@router.get("/{evaluation_id}/research-template")
async def download_research_template(
    evaluation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == tenant_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    workbook = build_research_workbook(record)
    safe_address = "".join(ch if ch.isalnum() else "_" for ch in (record.address or "未知地址"))[:40].strip("_") or "未知地址"
    filename = f"选址调研明细_{safe_address}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
    }
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/{evaluation_id}/research-import")
async def import_research_template(
    evaluation_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == tenant_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 格式的调研明细表")
    try:
        parsed = parse_research_workbook(file.file)
    except Exception as exc:
        logger.warning("调研明细表解析失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=f"调研明细表解析失败：{str(exc)[:120]}")
    return {
        "evaluation_id": record.id,
        "filename": file.filename,
        **parsed,
    }


@router.post("/{evaluation_id}/research-import/confirm")
async def confirm_research_import(
    evaluation_id: int,
    req: ResearchImportConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == tenant_id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="评估记录不存在")
    record.manual_data = req.manual_data or {}
    db.commit()
    db.refresh(record)
    research_status = build_research_required_fields(record.manual_data or {})
    research_tables = build_research_tables(record.dimensions or {}, record.manual_data or {})
    return {
        "message": "调研明细表已确认并保存为草稿",
        "evaluation_id": record.id,
        "manual_data": record.manual_data or {},
        "research_required_fields": research_status["items"],
        "research_completion_rate": research_status["completion_rate"],
        "confirmed_poi_tables": research_tables["confirmed"],
        "excluded_poi_tables": research_tables["excluded"],
    }


@router.post("/{evaluation_id}/feedback")
async def submit_evaluation_feedback(
    evaluation_id: int,
    req: EvaluationFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = current_user.tenant_id or 1
    record = db.query(EvaluationRecord).filter(
        EvaluationRecord.id == evaluation_id,
        EvaluationRecord.tenant_id == tenant_id,
    ).first()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="评估记录不存在")
    feedback = EvaluationFeedback(
        tenant_id=tenant_id,
        evaluation_id=evaluation_id,
        accurate_aspects=req.accurate_aspects or [],
        inaccurate_aspects=req.inaccurate_aspects or [],
        abnormal_data=req.abnormal_data or [],
        actual_daily_customers=req.actual_daily_customers,
        actual_monthly_revenue=req.actual_monthly_revenue,
        actual_monthly_profit=req.actual_monthly_profit,
        actual_occupancy_rate=req.actual_occupancy_rate,
        actual_member_growth=req.actual_member_growth,
        notes=req.notes,
        created_by=current_user.id,
    )
    db.add(feedback)
    sync_feedback_and_quality_insights(db, tenant_id)
    db.commit()
    return {"message": "反馈已保存，将进入下一轮历史分析", "feedback_id": feedback.id}


def _evaluation_payload(record: EvaluationRecord, include_detail: bool = False) -> dict:
    data = {
        "id": record.id,
        "address": record.address,
        "longitude": record.longitude,
        "latitude": record.latitude,
        "radius": record.radius,
        "total_score": record.total_score,
        "grade": record.grade,
        "grade_label": record.grade_label,
        "model_version_id": record.model_version_id,
        "data_quality": record.data_quality,
        "is_excluded": record.is_excluded,
        "exclude_reason": record.exclude_reason,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
    if include_detail:
        research_status = build_research_required_fields(record.manual_data or {})
        research_tables = build_research_tables(record.dimensions or {}, record.manual_data or {})
        data.update({
            "evaluation_id": record.id,
            "dimensions": record.dimensions,
            "normalized_weights": record.normalized_weights,
            "manual_data": record.manual_data,
            "llm_report": record.llm_report,
            "rag_evidence": record.rag_evidence,
            "research_required_fields": research_status["items"],
            "research_completion_rate": research_status["completion_rate"],
            "confirmed_poi_tables": research_tables["confirmed"],
            "excluded_poi_tables": research_tables["excluded"],
        })
    return data


class HeatmapRequest(BaseModel):
    longitude: float
    latitude: float
    radius: int = 2000  # 热力图半径（米）
    allow_mock_data: bool = False


@router.post("/heatmap")
async def get_heatmap(
    req: HeatmapRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取消费热力图数据
    - 优先使用高德慧眼企业 API（需在系统配置中填写 amap_huiyan_key）
    - 未配置慧眼 Key 时，必须由用户明确授权后才允许使用 POI 密度模拟
    """
    from app.services.amap import get_amap_key, get_huiyan_key, get_heatmap_data

    amap_key = get_amap_key(db)
    if not amap_key:
        return {"source": "none", "points": [], "message": "未配置高德 API Key"}

    huiyan_key = get_huiyan_key(db)
    source = "huiyan" if huiyan_key else "poi_simulation"
    if not huiyan_key and not req.allow_mock_data:
        return {
            "source": "requires_mock_authorization",
            "points": [],
            "total": 0,
            "message": "未配置高德慧眼真实消费热力数据。请配置慧眼 Key，或明确点击“使用模拟数据”后再加载 POI 密度模拟热力图。"
        }

    try:
        points = await get_heatmap_data(
            longitude=req.longitude,
            latitude=req.latitude,
            radius=req.radius,
            api_key=amap_key,
            huiyan_key=huiyan_key,
            allow_mock_data=req.allow_mock_data
        )
        return {
            "source": source,
            "points": points,
            "total": len(points),
            "message": "慧眼精准消费数据" if huiyan_key else "POI 密度模拟数据（如需精准消费热力，请配置高德慧眼 Key）"
        }
    except Exception as e:
        logger.error(f"热力图数据获取失败: {e}")
        return {"source": "error", "points": [], "message": str(e)[:100]}


class SimilarCasesRequest(BaseModel):
    address: str
    total_score: Optional[float] = None
    top_k: int = 3


@router.post("/similar-cases")
async def get_similar_cases(
    req: SimilarCasesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取历史相似案例推荐
    基于当前评估地址，从知识库中检索最相似的历史门店案例
    """
    from app.services.vector_rag import hybrid_search
    from app.models.store import Store

    tenant_id = current_user.tenant_id

    try:
        # 构建查询文本：地址 + 评分
        query = f"选址评估 {req.address}"
        if req.total_score:
            query += f" 综合得分{req.total_score:.0f}分"

        # 从知识库检索相似案例（只检索门店经验类型）
        candidates = await hybrid_search(
            query=query,
            tenant_id=tenant_id,
            db=db,
            source_types=["store_experience", "evaluation_result", "document_experience"],
            top_k=req.top_k * 2,  # 多取一些，后面过滤
        )

        # 构建结果，附加门店详情
        results = []
        seen_store_ids = set()

        for c in candidates:
            meta = c.get("metadata", {})
            store_id = meta.get("store_id")
            source_type = c.get("source_type")

            # 评估结果类型：直接从 metadata 构建卡片
            if source_type == "evaluation_result":
                card = {
                    "type": "evaluation",
                    "address": meta.get("address", ""),
                    "total_score": meta.get("total_score"),
                    "grade": meta.get("grade", ""),
                    "grade_label": meta.get("grade_label", ""),
                    "similarity": round(c.get("fusion_score", 0) * 100, 1),
                    "summary": c.get("content", "")[:200],
                    "evaluated_at": meta.get("evaluated_at", ""),
                }
                results.append(card)

            elif source_type == "document_experience":
                card = {
                    "type": "document",
                    "document_id": meta.get("document_id"),
                    "filename": meta.get("filename", ""),
                    "scope_type": meta.get("scope_type", "brand"),
                    "candidate_address": meta.get("candidate_address", ""),
                    "similarity": round(c.get("fusion_score", 0) * 100, 1),
                    "summary": c.get("content", "")[:200],
                }
                results.append(card)

            # 门店经验类型：查询门店详情
            elif source_type == "store_experience" and store_id and store_id not in seen_store_ids:
                seen_store_ids.add(store_id)
                store = db.query(Store).filter(
                    Store.id == store_id,
                    Store.tenant_id == tenant_id
                ).first()
                if store:
                    card = {
                        "type": "store",
                        "store_id": store.id,
                        "name": store.name,
                        "address": store.address or "",
                        "city": store.city or "",
                        "district": store.district or "",
                        "area_sqm": store.area_sqm,
                        "machine_count": store.machine_count,
                        "monthly_rent": store.monthly_rent,
                        "status": store.status,
                        "is_success": store.is_success,
                        "experience_notes": store.experience_notes or "",
                        "similarity": round(c.get("fusion_score", 0) * 100, 1),
                        "summary": c.get("content", "")[:200],
                    }
                    results.append(card)

            if len(results) >= req.top_k:
                break

        return {
            "cases": results,
            "total": len(results),
            "message": f"找到 {len(results)} 个相似历史案例" if results else "暂无相似历史案例，上传历史门店数据后将自动积累案例库"
        }

    except Exception as e:
        logger.error(f"相似案例检索失败: {e}")
        return {"cases": [], "total": 0, "message": "检索失败，请稍后重试"}


class CompareRequest(BaseModel):
    addresses: list[str]  # 2-3 个候选地址
    radius: int = 1500
    allow_mock_data: bool = False
    manual_data: Optional[dict] = None


@router.post("/compare")
async def compare_locations(
    req: CompareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    多地址对比评估（SSE 流式输出）
    同时评估 2-3 个候选地址，输出对比结果和 AI 推荐分析
    """
    if len(req.addresses) < 2 or len(req.addresses) > 3:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="请提供 2-3 个候选地址")

    tenant_id = current_user.tenant_id
    addresses = [a.strip() for a in req.addresses if a.strip()]
    labels = ['A', 'B', 'C'][:len(addresses)]
    radius = req.radius
    allow_mock_data = req.allow_mock_data
    manual_data = req.manual_data or {}

    async def event_stream():
        stream_db = SessionLocal()
        try:
            results = []

            # 逐个评估候选地址
            for i, address in enumerate(addresses):
                label = labels[i]
                yield f"data: {json.dumps({'type': 'executing', 'step': f'评估候选{label}', 'message': f'正在评估候选 {label}：{address}'}, ensure_ascii=False)}\n\n"

                result = None
                async for step in evaluate_location(
                    address=address,
                    city=None,
                    db=stream_db,
                    tenant_id=tenant_id,
                    radius=radius,
                    allow_mock_data=allow_mock_data,
                    manual_data=manual_data.get(label) or {},
                    generate_report=False,
                    store_knowledge=False,
                    created_by=current_user.id,
                ):
                    if step.get("type") == "final":
                        result = step
                    elif step.get("type") not in ("llm",):
                        # 转发工作流步骤（带标签）
                        step["message"] = f"[候选{label}] {step.get('message', '')}"
                        yield f"data: {json.dumps(step, ensure_ascii=False)}\n\n"

                if result:
                    result["label"] = label
                    results.append(result)
                    _score = result.get('total_score', 0)
                    # 立即推送单个地址的评估结果（partial_result），前端实时展示
                    _partial = {
                        'type': 'partial_result',
                        'result': {
                            'label': label,
                            'address': result.get('address', address),
                            'total_score': _score,
                            'grade': result.get('grade', 'C'),
                            'grade_label': result.get('grade_label', '谨慎评估'),
                            'data_quality': result.get('data_quality', {}),
                        }
                    }
                    yield f"data: {json.dumps(_partial, ensure_ascii=False)}\n\n"
                    _msg = {'type': 'result', 'step': f'候选{label}完成', 'message': f'候选 {label} 评估完成，综合得分 {_score} 分'}
                    yield f"data: {json.dumps(_msg, ensure_ascii=False)}\n\n"

            # 推送对比结果
            yield f"data: {json.dumps({'type': 'compare_result', 'results': results}, ensure_ascii=False)}\n\n"

            # 生成 AI 对比分析
            if results:
                yield f"data: {json.dumps({'type': 'thinking', 'step': 'AI分析', 'message': '正在生成 AI 综合对比分析...'}, ensure_ascii=False)}\n\n"

                from app.services.llm_gateway import chat_completion_stream
                compare_prompt = _build_compare_prompt(results)
                messages = [{"role": "user", "content": compare_prompt}]
                try:
                    async with asyncio.timeout(90):
                        async for chunk in chat_completion_stream(messages, stream_db):
                            yield f"data: {json.dumps({'type': 'llm', 'data': {'content': chunk}}, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    fallback = _build_compare_fallback(results)
                    yield f"data: {json.dumps({'type': 'warning', 'step': 'AI分析', 'message': 'AI 综合分析超过 90 秒，已先返回评分结果和规则摘要。请检查模型服务速度或改用更快模型。'}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'llm', 'data': {'content': fallback}}, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"对比评估失败: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'step': '错误', 'message': f'对比评估失败：{str(e)[:100]}'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


def _build_compare_prompt(results: list[dict]) -> str:
    compare_prompt = "你是专业的电竞馆选址顾问。以下是对多个候选地址的评估结果，请给出专业的对比分析和最终推荐意见。若数据来源包含模拟数据，必须在报告开头明确提示。请直接开始分析。\n\n"
    for r in results:
        compare_prompt += f"**候选 {r['label']}**（{r.get('address', '')}）\n"
        compare_prompt += f"- 综合得分：{r.get('total_score', 0)} 分（{r.get('grade_label', '')}）\n"
        quality = r.get("data_quality", {})
        if quality.get("has_simulation"):
            compare_prompt += "- 数据提示：包含模拟或中性估算数据，结论仅可作为初筛参考\n"
        dims = r.get("dimensions", {})
        for key, dim in dims.items():
            dim_names = {"traffic": "交通", "competition": "竞品", "population": "客群",
                         "rent": "租金", "facility": "配套", "policy": "政策"}
            source_label = dim.get("source_label") or ("模拟/估算数据" if dim.get("is_simulated") else "外部真实数据")
            poi_text = ""
            evidence_pois = dim.get("evidence_pois") or []
            if evidence_pois:
                poi_parts = []
                for poi in evidence_pois[:5]:
                    distance = poi.get("distance")
                    suffix = f"{distance}m" if isinstance(distance, int) else "距离未知"
                    poi_parts.append(f"{poi.get('name')}({suffix})")
                poi_text = f"；地图证据：{'、'.join(poi_parts)}"
            if dim.get("is_simulated"):
                poi_text += "；注意：该维度未使用真实外部数据"
            compare_prompt += f"- {dim_names.get(key, key)}：{dim.get('score', 0)}分，数据来源：{source_label} - {dim.get('detail', '')}{poi_text}\n"
        evidence = r.get("rag_evidence") or []
        if evidence:
            compare_prompt += "- 历史经验/调研文档依据：\n"
            for item in evidence[:2]:
                compare_prompt += f"  - {item.get('source_name', '历史知识')}：{item.get('content', '')[:120]}\n"
        compare_prompt += "\n"

    compare_prompt += "\n请从以下角度进行分析：\n1. 各候选地址的核心优势和劣势\n2. 维度得分的关键差异\n3. 数据真实性与缺失项对结论的影响\n4. 适合不同经营策略的推荐\n5. 最终推荐排名及理由\n6. 需要重点补充的真实数据\n\n数据使用要求：只能引用上方已提供的真实 POI、用户补充数据、历史经验；不得编造地图信息或距离；未使用真实数据的部分必须明确标注。"
    return compare_prompt


def _build_compare_fallback(results: list[dict]) -> str:
    ordered = sorted(results, key=lambda item: item.get("total_score", 0), reverse=True)
    lines = ["## 规则摘要", "", "AI 模型响应较慢，系统先基于评分结果生成摘要。", "", "### 推荐排序"]
    for idx, item in enumerate(ordered, start=1):
        lines.append(f"{idx}. 候选 {item.get('label')}：{item.get('address')}，{item.get('total_score')} 分，{item.get('grade_label')}")
    lines.append("")
    lines.append("### 后续建议")
    lines.append("- 优先补齐租金、面积、政策/消防/证照限制等客户侧真实数据。")
    lines.append("- 若存在模拟数据，本次结果只能用于初筛，正式投资决策前应替换为真实数据重新生成报告。")
    return "\n".join(lines)


class ExportReportRequest(BaseModel):
    evaluation_result: dict
    ai_report: Optional[str] = ""
    similar_cases: Optional[list] = []
    format: Optional[str] = "html"


@router.post("/export-report")
async def export_evaluation_report(
    req: ExportReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    导出评估报告为 PDF
    接收前端传来的评估结果数据，生成专业 PDF 报告并返回文件流
    """
    try:
        from fastapi.responses import Response
        from urllib.parse import quote
        from app.services.report_generator import generate_evaluation_report_html, generate_evaluation_report_pdf

        address = req.evaluation_result.get("address", "选址报告")[:20]
        date_str = datetime.now().strftime("%Y%m%d")

        if (req.format or "html").lower() == "html":
            html_content = generate_evaluation_report_html(
                evaluation_result=req.evaluation_result,
                ai_report=req.ai_report or "",
                similar_cases=req.similar_cases or []
            )
            filename = f"选址评估报告_{address}_{date_str}.html"
            encoded_filename = quote(filename, safe='')
            return Response(
                content=html_content.encode("utf-8"),
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                    "Content-Length": str(len(html_content.encode("utf-8"))),
                }
            )

        pdf_bytes = generate_evaluation_report_pdf(
            evaluation_result=req.evaluation_result,
            ai_report=req.ai_report or "",
            similar_cases=req.similar_cases or []
        )

        filename = f"选址评估报告_{address}_{date_str}.pdf"
        # 对文件名进行 URL 编码
        encoded_filename = quote(filename, safe='')

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "Content-Length": str(len(pdf_bytes)),
            }
        )
    except Exception as e:
        logger.error(f"PDF 生成失败: {e}", exc_info=True)
        # 降级为 Markdown
        from fastapi.responses import Response as FastAPIResponse
        md_content = _build_markdown_report(req.evaluation_result, req.ai_report or "")
        return FastAPIResponse(
            content=md_content.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=report.md"
            }
        )


def _build_markdown_report(evaluation_result: dict, ai_report: str) -> str:
    """降级方案：生成 Markdown 格式报告"""
    address = evaluation_result.get("address", "未知地址")
    total_score = evaluation_result.get("total_score", 0)
    grade = evaluation_result.get("grade", "C")
    grade_label = evaluation_result.get("grade_label", "一般")
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    lines = [
        f"# 电竞馆智能选址评估报告",
        f"",
        f"**评估地址**：{address}",
        f"**综合得分**：{total_score} 分",
        f"**评级**：{grade}级 - {grade_label}",
        f"**报告时间**：{now}",
        f"",
        f"---",
        f"",
        f"## 一、六维评分详情",
        f"",
        f"| 评分维度 | 得分 | 详情说明 |",
        f"|---------|------|---------|",
    ]

    dim_names = {
        "traffic": "交通便利性", "competition": "竞品分析",
        "population": "客群密度", "rent": "租金成本",
        "facility": "配套设施", "policy": "政策环境"
    }
    for key, dim in evaluation_result.get("dimensions", {}).items():
        lines.append(f"| {dim_names.get(key, key)} | {dim.get('score', 0)}分 | {dim.get('detail', '')} |")

    if ai_report:
        lines.extend(["", "---", "", "## 二、AI 深度分析报告", "", ai_report])

    lines.extend(["", "---", "", f"*本报告由电竞馆智能选址系统自动生成，仅供参考*"])
    return "\n".join(lines)
