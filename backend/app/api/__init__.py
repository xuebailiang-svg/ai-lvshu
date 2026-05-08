from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.config import router as config_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["认证"])
router.include_router(config_router, prefix="/system/config", tags=["系统配置"])

@router.get("/health", tags=["系统"])
def health_check():
    return {"status": "ok", "service": "Esports Site Selection API"}
