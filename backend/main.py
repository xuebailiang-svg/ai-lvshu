from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import router as api_router
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.init_db import init_db

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="电竞馆智能选址系统 API",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境请修改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.on_event("startup")
def on_startup():
    """应用启动时自动初始化数据库"""
    db = SessionLocal()
    try:
        init_db(db)
    finally:
        db.close()

@app.get("/")
def root():
    return {
        "message": "电竞馆智能选址系统 API",
        "docs": f"{settings.API_V1_STR}/docs"
    }
