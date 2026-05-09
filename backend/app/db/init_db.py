import logging
from sqlalchemy.orm import Session
from app.db.base_class import Base
from app.db.session import engine
from app.models.user import User, Tenant
from app.models.system_config import SystemConfig
from app.models.store import Store, UploadRecord, RevenueRecord, MemberProfile, HardwareConfig, ScoringRule
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def init_db(db: Session) -> None:
    """初始化数据库：创建所有表并写入默认数据"""
    # 创建所有 ORM 表（不含 pgvector 向量表，那些在 init_ai_tables 中单独处理）
    Base.metadata.create_all(bind=engine)
    logger.info("[init_db] ORM 表创建完成")

    # 创建默认租户
    tenant = db.query(Tenant).filter(Tenant.name == "默认租户").first()
    if not tenant:
        tenant = Tenant(name="默认租户", is_active=True)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        logger.info("[init_db] 默认租户已创建")

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
        logger.info("[init_db] 管理员账号已创建 (admin / admin123)")

    # 写入默认系统配置（空值占位，用户通过配置面板填写）
    default_configs = [
        {"config_key": "llm.type",          "config_type": "llm",       "description": "大模型类型: api 或 local"},
        {"config_key": "llm.api_key",       "config_type": "llm",       "description": "大模型 API Key（API 模式）",       "is_encrypted": True},
        {"config_key": "llm.api_base",      "config_type": "llm",       "description": "大模型 API Base URL"},
        {"config_key": "llm.model_name",    "config_type": "llm",       "description": "大模型名称，如 qwen2.5:32b"},
        {"config_key": "llm.local_url",     "config_type": "llm",       "description": "本地大模型地址，如 http://localhost:11434/v1"},
        {"config_key": "embed.type",        "config_type": "embedding", "description": "向量模型类型: api 或 local"},
        {"config_key": "embed.api_key",     "config_type": "embedding", "description": "向量模型 API Key",                "is_encrypted": True},
        {"config_key": "embed.model_name",  "config_type": "embedding", "description": "向量模型名称，如 bge-m3:latest"},
        {"config_key": "embed.local_url",   "config_type": "embedding", "description": "本地向量模型地址，如 http://localhost:11434/api/embeddings"},
        {"config_key": "rerank.type",       "config_type": "reranker",  "description": "重排模型类型: api / local / none"},
        {"config_key": "rerank.api_key",    "config_type": "reranker",  "description": "重排模型 API Key",                "is_encrypted": True},
        {"config_key": "rerank.model_name", "config_type": "reranker",  "description": "重排模型名称"},
        {"config_key": "rerank.local_url",  "config_type": "reranker",  "description": "本地重排模型地址"},
        {"config_key": "amap_api_key",      "config_type": "map",       "description": "高德地图 Web 服务 API Key",        "is_encrypted": True},
        {"config_key": "meituan.api_key",   "config_type": "map",       "description": "美团 API Key",                    "is_encrypted": True},
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

    # 初始化默认评分规则（六大维度）
    default_rules = [
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "foot_traffic",          "base_weight": 0.25},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "transit_accessibility", "base_weight": 0.10},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_count",      "base_weight": 0.20},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_distance",   "base_weight": 0.05},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "young_density",         "base_weight": 0.20},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "university_nearby",     "base_weight": 0.05},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "rent_ratio",            "base_weight": 0.10},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "commercial_density",    "base_weight": 0.03},
        {"dimension": "policy",      "dimension_name": "政策环境",   "sub_factor": "policy_risk",           "base_weight": 0.02},
    ]
    for rule_data in default_rules:
        exists = db.query(ScoringRule).filter(
            ScoringRule.tenant_id == tenant.id,
            ScoringRule.dimension == rule_data["dimension"],
            ScoringRule.sub_factor == rule_data["sub_factor"]
        ).first()
        if not exists:
            db.add(ScoringRule(
                tenant_id=tenant.id,
                dimension=rule_data["dimension"],
                dimension_name=rule_data["dimension_name"],
                sub_factor=rule_data["sub_factor"],
                base_weight=rule_data["base_weight"],
                effective_weight=rule_data["base_weight"],
                last_updated_by="system",
            ))

    db.commit()
    logger.info("[init_db] 数据库初始化完成（含评分规则）")


async def init_ai_tables(db: Session) -> None:
    """
    初始化 AI 相关表（向量表、记忆表）—— 需要 pgvector 扩展。
    此函数失败不影响系统核心功能（登录、评分等），仅影响 RAG 检索功能。
    """
    try:
        from app.services.vector_rag import ensure_vector_table
        from app.services.memory import ensure_memory_tables
        await ensure_vector_table(db)
        await ensure_memory_tables(db)
        logger.info("[init_db] AI 向量表和记忆表初始化完成")
    except Exception as e:
        logger.warning(f"[init_db] AI 表初始化跳过（pgvector 可能未安装或配置未就绪）: {e}")
        logger.warning("[init_db] 系统核心功能（登录/评分/地图）不受影响，RAG 功能在配置模型后自动激活")
