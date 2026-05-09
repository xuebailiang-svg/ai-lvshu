"""
系统配置 API
- GET  /api/v1/system/config          - 获取所有配置（列表格式，前端直接用）
- POST /api/v1/system/config/batch    - 批量更新配置
- POST /api/v1/system/config/test     - 测试服务连通性
"""
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_superuser
from app.models.user import User
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)
router = APIRouter()

SENSITIVE_KEYS = {"amap_api_key", "amap_js_key", "amap_security_code",
                  "llm.api_key", "embed.api_key", "rerank.api_key", "meituan.api_key"}


class BatchUpdateRequest(BaseModel):
    configs: dict


class TestRequest(BaseModel):
    type: str  # llm / embedding / amap


def _get_config_value(db: Session, key: str) -> Optional[str]:
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    return cfg.config_value if cfg else None


@router.get("/", summary="获取所有系统配置（列表格式）")
def get_all_configs(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser)
):
    configs = db.query(SystemConfig).filter(SystemConfig.is_active == True).all()
    result = []
    for cfg in configs:
        value = cfg.config_value
        if cfg.config_key in SENSITIVE_KEYS and value and len(value) > 4:
            value = "****" + value[-4:]
        result.append({
            "config_key": cfg.config_key,
            "config_value": value,
            "config_type": cfg.config_type,
            "description": cfg.description,
        })
    return result


@router.post("/batch", summary="批量更新配置项")
def batch_update_configs(
    body: BatchUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser)
):
    updated = []
    created = []
    for key, value in body.configs.items():
        if value is None:
            continue
        cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if cfg:
            if isinstance(value, str) and value.startswith("****"):
                continue
            cfg.config_value = str(value)
            updated.append(key)
        else:
            config_type = key.split(".")[0] if "." in key else "general"
            new_cfg = SystemConfig(
                config_key=key,
                config_value=str(value),
                config_type=config_type,
                is_active=True,
            )
            db.add(new_cfg)
            created.append(key)
    db.commit()
    return {"updated": updated, "created": created, "total": len(updated) + len(created)}


@router.post("/test", summary="测试服务连通性")
async def test_connection(
    body: TestRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_superuser)
):
    if body.type == "llm":
        llm_type = _get_config_value(db, "llm.type") or "local"
        if llm_type == "local":
            base_url = _get_config_value(db, "llm.local_url") or "http://localhost:11434/v1"
            api_key = "ollama"
        else:
            base_url = _get_config_value(db, "llm.api_base") or "https://api.openai.com/v1"
            api_key = _get_config_value(db, "llm.api_key") or ""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("id", "") for m in data.get("data", [])]
                    return {"success": True, "message": f"连接成功，可用模型: {', '.join(models[:5])}"}
                else:
                    return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

    elif body.type == "embedding":
        embed_type = _get_config_value(db, "embed.type") or "local"
        base_url = _get_config_value(db, "embed.local_url") or "http://localhost:11434/api/embeddings"
        model = _get_config_value(db, "embed.model_name") or "bge-m3:latest"
        if embed_type == "local":
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(base_url, json={"model": model, "prompt": "测试连接"})
                    if resp.status_code == 200:
                        dim = len(resp.json().get("embedding", []))
                        return {"success": True, "message": f"连接成功，向量维度: {dim}"}
                    else:
                        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"连接失败: {str(e)}"}
        else:
            api_key = _get_config_value(db, "embed.api_key") or ""
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{base_url.rstrip('/')}/embeddings",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"model": model, "input": "测试连接"}
                    )
                    if resp.status_code == 200:
                        dim = len(resp.json().get("data", [{}])[0].get("embedding", []))
                        return {"success": True, "message": f"连接成功，向量维度: {dim}"}
                    else:
                        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"连接失败: {str(e)}"}

    elif body.type == "amap":
        api_key = _get_config_value(db, "amap_api_key")
        if not api_key:
            return {"success": False, "message": "高德 API Key 未配置，请先在地图 API Tab 填写"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://restapi.amap.com/v3/geocode/geo",
                    params={"address": "北京市天安门", "key": api_key}
                )
                data = resp.json()
                if data.get("status") == "1":
                    return {"success": True, "message": "高德 API 连接成功，地理编码服务正常"}
                else:
                    info = data.get("info", "未知错误")
                    infocode = data.get("infocode", "")
                    return {"success": False, "message": f"高德 API 返回错误: {info} (code: {infocode})"}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

    else:
        raise HTTPException(status_code=400, detail=f"不支持的测试类型: {body.type}")
