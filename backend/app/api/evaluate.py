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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.models.user import User
from app.models.store import Store, ScoringRule
from app.services.scoring import evaluate_location

logger = logging.getLogger(__name__)
router = APIRouter(tags=["评估"])


class EvaluateRequest(BaseModel):
    address: str
    city: Optional[str] = None
    radius: int = 1500  # 评估半径（米）


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
    async def event_stream():
        try:
            async for step in evaluate_location(
                address=req.address,
                city=req.city,
                db=db,
                tenant_id=current_user.tenant_id,
                radius=req.radius
            ):
                data = json.dumps(step, ensure_ascii=False)
                yield f"data: {data}\n\n"
                await asyncio.sleep(0.05)  # 控制推送节奏

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"评估异常: {e}")
            error_data = json.dumps({
                "type": "error",
                "step": "系统错误",
                "message": str(e),
                "data": {}
            }, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


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
