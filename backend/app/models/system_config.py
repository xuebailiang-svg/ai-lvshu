from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from datetime import datetime
from app.db.base_class import Base

class SystemConfig(Base):
    """系统配置表 - 管理所有外部服务的连接配置"""
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), unique=True, nullable=False, comment="配置键名")
    config_value = Column(Text, nullable=True, comment="配置值（敏感信息加密存储）")
    config_type = Column(String(50), nullable=False, comment="配置类型: llm/embedding/reranker/map/db")
    description = Column(String(200), nullable=True, comment="配置说明")
    is_encrypted = Column(Boolean, default=False, comment="是否加密存储")
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 配置键名约定：
    # LLM:       llm.type (api/local), llm.api_key, llm.api_base, llm.model_name, llm.local_url
    # Embedding: embed.type (api/local), embed.api_key, embed.model_name, embed.local_url
    # Reranker:  rerank.type (api/local), rerank.api_key, rerank.model_name, rerank.local_url
    # Map:       amap.api_key, meituan.api_key
    # DB:        db.host, db.port, db.name, db.user, db.password
