from sqlalchemy.orm import Session
from app.db.base_class import Base
from app.db.session import engine
from app.models.user import User, Tenant
from app.models.system_config import SystemConfig
from app.core.security import get_password_hash

def init_db(db: Session) -> None:
    """初始化数据库：创建所有表并写入默认数据"""
    Base.metadata.create_all(bind=engine)

    # 创建默认租户
    tenant = db.query(Tenant).filter(Tenant.name == "默认租户").first()
    if not tenant:
        tenant = Tenant(name="默认租户", is_active=True)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

    # 创建超级管理员
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            email="admin@esports-site.local",
            hashed_password=get_password_hash("admin123"),
            full_name="系统管理员",
            is_superuser=True,
            is_active=True,
            tenant_id=tenant.id,
        )
        db.add(admin)
        db.commit()

    # 写入默认系统配置（空值占位，用户通过配置面板填写）
    default_configs = [
        {"config_key": "llm.type",        "config_type": "llm",       "description": "大模型类型: api 或 local"},
        {"config_key": "llm.api_key",     "config_type": "llm",       "description": "大模型 API Key（API 模式）",      "is_encrypted": True},
        {"config_key": "llm.api_base",    "config_type": "llm",       "description": "大模型 API Base URL"},
        {"config_key": "llm.model_name",  "config_type": "llm",       "description": "大模型名称，如 gpt-4o / qwen-max"},
        {"config_key": "llm.local_url",   "config_type": "llm",       "description": "本地大模型地址，如 http://localhost:11434"},
        {"config_key": "embed.type",      "config_type": "embedding",  "description": "向量模型类型: api 或 local"},
        {"config_key": "embed.api_key",   "config_type": "embedding",  "description": "向量模型 API Key",               "is_encrypted": True},
        {"config_key": "embed.model_name","config_type": "embedding",  "description": "向量模型名称"},
        {"config_key": "embed.local_url", "config_type": "embedding",  "description": "本地向量模型地址"},
        {"config_key": "rerank.type",     "config_type": "reranker",   "description": "重排模型类型: api 或 local"},
        {"config_key": "rerank.api_key",  "config_type": "reranker",   "description": "重排模型 API Key",               "is_encrypted": True},
        {"config_key": "rerank.model_name","config_type": "reranker",  "description": "重排模型名称"},
        {"config_key": "rerank.local_url","config_type": "reranker",   "description": "本地重排模型地址"},
        {"config_key": "amap.api_key",    "config_type": "map",        "description": "高德地图 Web 服务 API Key",       "is_encrypted": True},
        {"config_key": "meituan.api_key", "config_type": "map",        "description": "美团 API Key",                   "is_encrypted": True},
    ]
    for cfg in default_configs:
        exists = db.query(SystemConfig).filter(SystemConfig.config_key == cfg["config_key"]).first()
        if not exists:
            db.add(SystemConfig(
                config_key=cfg["config_key"],
                config_value=None,
                config_type=cfg["config_type"],
                description=cfg.get("description", ""),
                is_encrypted=cfg.get("is_encrypted", False),
            ))
    db.commit()
    print("[init_db] 数据库初始化完成")
