from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_superuser
from app.models.user import User
from app.models.system_config import SystemConfig
from app.schemas.system_config import SystemConfigOut, SystemConfigUpdate, SystemConfigGroupOut

router = APIRouter()

MASKED = "******"  # 加密字段脱敏占位符

def _mask_config(cfg: SystemConfig) -> SystemConfigOut:
    """对加密字段进行脱敏处理"""
    out = SystemConfigOut.model_validate(cfg)
    if cfg.is_encrypted and cfg.config_value:
        out.config_value = MASKED
    return out

@router.get("/", response_model=SystemConfigGroupOut, summary="获取所有系统配置（按类型分组）")
def get_all_configs(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser)
):
    """获取所有配置项，敏感字段脱敏显示"""
    configs = db.query(SystemConfig).filter(SystemConfig.is_active == True).all()
    result = SystemConfigGroupOut()
    for cfg in configs:
        masked = _mask_config(cfg)
        if cfg.config_type == "llm":
            result.llm.append(masked)
        elif cfg.config_type == "embedding":
            result.embedding.append(masked)
        elif cfg.config_type == "reranker":
            result.reranker.append(masked)
        elif cfg.config_type == "map":
            result.map.append(masked)
    return result

@router.put("/{config_key}", response_model=SystemConfigOut, summary="更新指定配置项")
def update_config(
    config_key: str,
    config_in: SystemConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser)
):
    """更新指定配置项的值（仅超级管理员可操作）"""
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == config_key).first()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"配置项 '{config_key}' 不存在")

    if config_in.config_value is not None:
        cfg.config_value = config_in.config_value
    if config_in.is_active is not None:
        cfg.is_active = config_in.is_active
    db.commit()
    db.refresh(cfg)
    return _mask_config(cfg)

@router.post("/batch", summary="批量更新配置项")
def batch_update_configs(
    updates: dict,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser)
):
    """批量更新配置，key 为 config_key，value 为新值"""
    updated = []
    for key, value in updates.items():
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if cfg:
            cfg.config_value = value
            updated.append(key)
    db.commit()
    return {"updated": updated, "count": len(updated)}

@router.get("/test/{config_type}", summary="测试指定类型的服务连通性")
def test_connection(
    config_type: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser)
):
    """测试 LLM / 向量模型 / 高德 API 等服务的连通性"""
    # TODO: 阶段4实现具体连通性测试逻辑
    return {"config_type": config_type, "status": "pending", "message": "连通性测试将在后续阶段实现"}
