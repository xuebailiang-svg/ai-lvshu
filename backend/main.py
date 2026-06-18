from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api import router as api_router
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.init_db import init_db, init_ai_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    db = SessionLocal()
    try:
        # 核心数据库初始化失败时必须终止启动，避免进程存活但 API 全部不可用。
        init_db(db)
        # AI 表是可选能力，其内部会记录异常并安全降级。
        await init_ai_tables(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="电竞馆智能选址系统 API",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {
        "message": "电竞馆智能选址系统 API",
        "docs": f"{settings.API_V1_STR}/docs",
        "version": "1.0.0"
    }
