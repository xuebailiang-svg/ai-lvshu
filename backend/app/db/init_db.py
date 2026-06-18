import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.base_class import Base
from app.db.session import engine
from app.core.config import settings
from app.models.user import User, Tenant
from app.models.system_config import SystemConfig
from app.models.store import (
    AnalysisInsight,
    CrawlEvidenceItem,
    CrawlJob,
    CrawlJobEvent,
    DataQualityIssue,
    EvaluationFeedback,
    EvaluationRecord,
    ExcludedKnowledgeSource,
    HardwareConfig,
    KnowledgeDocument,
    DocumentInsight,
    MemberProfile,
    RevenueRecord,
    ScoringModelVersion,
    ScoringRule,
    Store,
    UploadRecord,
)
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


def init_db(db: Session) -> None:
    """初始化数据库：创建所有表并写入默认数据"""
    Base.metadata.create_all(bind=engine)
    db.execute(text("ALTER TABLE crawl_evidence_items ADD COLUMN IF NOT EXISTS source_site VARCHAR(30)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_crawl_evidence_items_source_site ON crawl_evidence_items (source_site)"))
    db.commit()
    logger.info("[init_db] ORM 表创建完成")

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
        initial_password = settings.INITIAL_ADMIN_PASSWORD
        if not initial_password or len(initial_password) < 12:
            raise RuntimeError(
                "INITIAL_ADMIN_PASSWORD must be set to at least 12 characters when creating the initial admin"
            )
        admin = User(
            username="admin",
            email="admin@esports-site.local",
            hashed_password=get_password_hash(initial_password),
            full_name="系统管理员",
            is_superuser=True,
            is_active=True,
            tenant_id=tenant.id,
        )
        db.add(admin)
        db.commit()
        logger.info("[init_db] 初始管理员账号已创建；请使用安装程序输出的随机密码登录")

    # 写入默认系统配置（预填充 Ollama 本地模型默认值）
    default_configs = [
        # ===== 大模型 (LLM) =====
        {
            "config_key": "llm.type",
            "config_type": "llm",
            "config_value": "local",
            "description": "大模型类型: api（OpenAI兼容API）或 local（本地Ollama）",
        },
        {
            "config_key": "llm.local_url",
            "config_type": "llm",
            "config_value": "http://localhost:11434/v1",
            "description": "本地大模型 API 地址（Ollama OpenAI兼容接口）",
        },
        {
            "config_key": "llm.model_name",
            "config_type": "llm",
            "config_value": "qwen2.5:32b",
            "description": "大模型名称（本地模式填 ollama list 中的名称）",
        },
        {
            "config_key": "llm.api_key",
            "config_type": "llm",
            "config_value": "ollama",
            "description": "大模型 API Key（本地Ollama填 ollama 即可，API模式填真实Key）",
            "is_encrypted": True,
        },
        {
            "config_key": "llm.api_base",
            "config_type": "llm",
            "config_value": "",
            "description": "API 模式的 Base URL（如 https://api.openai.com/v1）",
        },
        {
            "config_key": "llm.fast_model",
            "config_type": "llm",
            "config_value": "qwen2.5:14b-instruct",
            "description": "快速推理模型（用于意图分析等轻量任务，响应更快）",
        },
        # ===== 嵌入模型 (Embedding) =====
        {
            "config_key": "embed.type",
            "config_type": "embedding",
            "config_value": "local",
            "description": "向量嵌入模型类型: api 或 local",
        },
        {
            "config_key": "embed.local_url",
            "config_type": "embedding",
            "config_value": "http://localhost:11434/api/embeddings",
            "description": "本地嵌入模型地址（Ollama 原生 embeddings 接口）",
        },
        {
            "config_key": "embed.model_name",
            "config_type": "embedding",
            "config_value": "bge-m3:latest",
            "description": "嵌入模型名称（推荐 bge-m3:latest，已在 Ollama 中部署）",
        },
        {
            "config_key": "embed.api_key",
            "config_type": "embedding",
            "config_value": "ollama",
            "description": "嵌入模型 API Key（本地填 ollama）",
            "is_encrypted": True,
        },
        # ===== 重排模型 (Reranker) =====
        {
            "config_key": "rerank.type",
            "config_type": "reranker",
            "config_value": "none",
            "description": "重排模型类型: none（跳过重排）/ local（本地BGE-Reranker）/ api（Cohere等）",
        },
        {
            "config_key": "rerank.local_url",
            "config_type": "reranker",
            "config_value": "",
            "description": "本地重排模型地址（如部署了 BGE-Reranker 填写）",
        },
        {
            "config_key": "rerank.model_name",
            "config_type": "reranker",
            "config_value": "",
            "description": "重排模型名称（如 BAAI/bge-reranker-v2-m3）",
        },
        {
            "config_key": "rerank.api_key",
            "config_type": "reranker",
            "config_value": "",
            "description": "重排模型 API Key（Cohere API 模式填写）",
            "is_encrypted": True,
        },
        # ===== 地图 API =====
        {
            "config_key": "amap_api_key",
            "config_type": "map",
            "config_value": "",
            "description": "高德地图 Web 服务 API Key（必填，用于地址解析和POI查询）",
            "is_encrypted": True,
        },
        {
            "config_key": "amap_js_key",
            "config_type": "map",
            "config_value": "",
            "description": "高德地图 JS API Key（前端地图显示，与 Web 服务 Key 可相同）",
            "is_encrypted": True,
        },
        {
            "config_key": "amap_security_code",
            "config_type": "map",
            "config_value": "",
            "description": "高德地图安全密钥（JS API 2.0 必须填写，在高德控制台获取）",
            "is_encrypted": True,
        },
        {
            "config_key": "meituan.api_key",
            "config_type": "map",
            "config_value": "",
            "description": "美团 API Key（可选，用于获取周边餐饮/娱乐POI数据）",
            "is_encrypted": True,
        },
        # ===== 公开信息采集服务 =====
        {"config_key": "crawler.enabled", "config_type": "crawler", "config_value": "false", "description": "是否启用公开信息采集"},
        {"config_key": "crawler.service_url", "config_type": "crawler", "config_value": "http://127.0.0.1:8010", "description": "内部采集服务地址"},
        {"config_key": "crawler.internal_token", "config_type": "crawler", "config_value": "", "description": "主后端访问采集服务的共享令牌", "is_encrypted": True},
        {"config_key": "crawler.auto_start", "config_type": "crawler", "config_value": "true", "description": "初版评估完成后是否自动启动采集"},
        {"config_key": "crawler.source.official", "config_type": "crawler", "config_value": "true", "description": "启用竞品和品牌官网采集"},
        {"config_key": "crawler.source.property", "config_type": "crawler", "config_value": "true", "description": "启用公开商铺房源采集"},
        {"config_key": "crawler.source.government", "config_type": "crawler", "config_value": "true", "description": "启用政府公开信息采集"},
        {"config_key": "crawler.site.baidu", "config_type": "crawler", "config_value": "true", "description": "使用百度发现公开网址，不采用搜索摘要"},
        {"config_key": "crawler.site.bing", "config_type": "crawler", "config_value": "true", "description": "使用 Bing 发现公开网址，不采用搜索摘要"},
        {"config_key": "crawler.site.official", "config_type": "crawler", "config_value": "true", "description": "采集竞品和品牌公开官网"},
        {"config_key": "crawler.site.58", "config_type": "crawler", "config_value": "true", "description": "采集 58 同城公开商铺房源"},
        {"config_key": "crawler.site.anjuke", "config_type": "crawler", "config_value": "true", "description": "采集安居客公开商铺房源"},
        {"config_key": "crawler.site.fang", "config_type": "crawler", "config_value": "true", "description": "采集房天下公开商铺房源"},
        {"config_key": "crawler.site.gov", "config_type": "crawler", "config_value": "true", "description": "采集 gov.cn 政府公开信息"},
        {"config_key": "crawler.timeout_seconds", "config_type": "crawler", "config_value": "300", "description": "单任务超时秒数"},
        {"config_key": "crawler.max_pages", "config_type": "crawler", "config_value": "20", "description": "单任务最多页面数"},
        {"config_key": "crawler.browser_pages", "config_type": "crawler", "config_value": "2", "description": "Chromium 最大页面数"},
    ]

    for cfg in default_configs:
        exists = db.query(SystemConfig).filter(SystemConfig.config_key == cfg["config_key"]).first()
        if not exists:
            db.add(SystemConfig(
                config_key=cfg["config_key"],
                config_value=cfg.get("config_value"),
                config_type=cfg["config_type"],
                description=cfg.get("description", ""),
                is_encrypted=cfg.get("is_encrypted", False),
            ))

    # 初始化默认评分规则（六大维度 + 可编辑细分因子）
    default_rules = [
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "foot_traffic",          "base_weight": 0.25},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "transit_accessibility", "base_weight": 0.10},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "metro_distance",        "base_weight": 0.00},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "bus_distance",          "base_weight": 0.00},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "negative_overpass",     "base_weight": 0.00},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "negative_interchange",  "base_weight": 0.00},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "negative_underpass",    "base_weight": 0.00},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "negative_railway",      "base_weight": 0.00},
        {"dimension": "traffic",     "dimension_name": "交通与人流", "sub_factor": "negative_greenbelt",    "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_count",      "base_weight": 0.20},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_distance",   "base_weight": 0.05},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_configuration", "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_price",      "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_occupancy",  "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_open_years", "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_area",       "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_monthly_sales", "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_annual_sales", "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "competitor_recharge",   "base_weight": 0.00},
        {"dimension": "competition", "dimension_name": "竞品分析",   "sub_factor": "same_category_capacity", "base_weight": 0.00},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "young_density",         "base_weight": 0.20},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "university_nearby",     "base_weight": 0.05},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "resident_population",   "base_weight": 0.00},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "floating_population",   "base_weight": 0.00},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "age_18_24",             "base_weight": 0.00},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "age_25_34",             "base_weight": 0.00},
        {"dimension": "population",  "dimension_name": "目标客群",   "sub_factor": "secondary_vocational_nearby", "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "rent_ratio",            "base_weight": 0.10},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "area_sqm",              "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "floor",                 "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "frontage_visibility",   "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "parking_convenience",   "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "fire_safety",           "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "property_restriction",  "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "power_capacity",        "base_weight": 0.00},
        {"dimension": "rent",        "dimension_name": "租金与成本", "sub_factor": "hvac_exhaust",          "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "commercial_density",    "base_weight": 0.03},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "night_market",          "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "food_business_hours",   "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "food_category",         "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "food_open_years",       "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "ktv",                   "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "bar",                   "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "billiards",             "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "escape_room",           "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "cinema",                "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "convenience_24h",       "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "relocation_housing",    "base_weight": 0.00},
        {"dimension": "facility",    "dimension_name": "配套设施",   "sub_factor": "apartment",             "base_weight": 0.00},
        {"dimension": "policy",      "dimension_name": "政策环境",   "sub_factor": "policy_risk",           "base_weight": 0.02},
        {"dimension": "policy",      "dimension_name": "政策环境",   "sub_factor": "policy_redline_200m",   "base_weight": 0.00},
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
    logger.info("[init_db] 数据库初始化完成（含评分规则和默认模型配置）")


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
        # 向量维度迁移：将旧表的 vector(384) 升级为 vector(1024)（bge-m3 维度）
        _migrate_vector_dimension(db)
        logger.info("[init_db] AI 向量表和记忆表初始化完成")
    except Exception as e:
        logger.warning(f"[init_db] AI 表初始化跳过（不影响核心功能）: {e}")
        logger.warning("[init_db] 系统核心功能（登录/评分/地图）不受影响，RAG 功能在配置模型后自动激活")


def _migrate_vector_dimension(db: Session) -> None:
    """
    将旧向量表的 embedding 列从 vector(384) 升级为 vector(1024)
    对于已经是 1024 维度的表，该操作不会执行（已经是正确维度）
    """
    tables = [
        ("knowledge_vectors", "embedding"),
        ("semantic_memories", "embedding"),
        ("episodic_memories", "embedding"),
    ]
    for table, col in tables:
        try:
            # 检查当前维度
            result = db.execute(text("""
                SELECT atttypmod FROM pg_attribute
                JOIN pg_class ON pg_class.oid = pg_attribute.attrelid
                WHERE pg_class.relname = :table AND pg_attribute.attname = :col
            """), {"table": table, "col": col}).fetchone()
            if result and result[0] == 384:
                logger.info(f"[migrate] 升级 {table}.{col}: vector(384) -> vector(1024)")
                db.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} vector(1024)"))
                db.commit()
                logger.info(f"[migrate] {table}.{col} 升级完成")
        except Exception as e:
            logger.warning(f"[migrate] {table} 维度迁移跳过: {e}")
            try:
                db.rollback()
            except Exception:
                pass
