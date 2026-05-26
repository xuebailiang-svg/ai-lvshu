from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.config import router as config_router
from app.api.data import router as data_router
from app.api.evaluate import router as evaluate_router
from app.api.chat import router as chat_router
from app.api.analysis import router as analysis_router
from app.api.model_versions import router as model_versions_router
from app.api.data_quality import router as data_quality_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["认证"])
router.include_router(config_router, prefix="/system/config", tags=["系统配置"])
router.include_router(data_router, prefix="/data", tags=["数据管理"])
router.include_router(analysis_router, prefix="/analysis", tags=["历史分析"])
router.include_router(model_versions_router, prefix="/model-versions", tags=["评分模型"])
router.include_router(data_quality_router, prefix="/data-quality", tags=["数据质量"])
router.include_router(evaluate_router, prefix="/evaluate", tags=["评估"])
router.include_router(chat_router, prefix="/chat", tags=["对话评估"])

@router.get("/health", tags=["系统"])
def health_check():
    return {"status": "ok", "service": "Esports Site Selection API"}
