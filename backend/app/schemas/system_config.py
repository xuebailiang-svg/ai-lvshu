from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class SystemConfigBase(BaseModel):
    config_key: str
    config_type: str
    description: Optional[str] = None

class SystemConfigUpdate(BaseModel):
    config_value: Optional[str] = None
    is_active: Optional[bool] = None

class SystemConfigOut(SystemConfigBase):
    id: int
    config_value: Optional[str] = None  # 加密字段返回时脱敏
    is_encrypted: bool
    is_active: bool
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SystemConfigGroupOut(BaseModel):
    """按类型分组返回的配置"""
    llm: list[SystemConfigOut] = []
    embedding: list[SystemConfigOut] = []
    reranker: list[SystemConfigOut] = []
    map: list[SystemConfigOut] = []
