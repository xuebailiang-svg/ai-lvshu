"""
系统配置 API
- GET  /api/v1/system/config/         - 获取所有配置（列表格式，前端直接用）
- POST /api/v1/system/config/batch    - 批量更新配置
- POST /api/v1/system/config/test     - 测试服务连通性
"""
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_current_superuser, get_current_user
from app.models.user import User
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)
router = APIRouter()

SENSITIVE_KEYS = {"amap_api_key", "amap_js_key", "amap_security_code",
                  "llm.api_key", "embed.api_key", "rerank.api_key", "meituan.api_key"}


class BatchUpdateRequest(BaseModel):
    configs: dict


class TestRequest(BaseModel):
    type: str                        # llm / embedding / amap
    # 可选：前端把当前表单值一起传来，优先使用，避免依赖数据库未保存的配置
    llm_type: Optional[str] = None
    llm_local_url: Optional[str] = None
    llm_api_base: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model_name: Optional[str] = None
    embed_type: Optional[str] = None
    embed_local_url: Optional[str] = None
    embed_model_name: Optional[str] = None
    embed_api_key: Optional[str] = None
    amap_api_key: Optional[str] = None


def _get_config_value(db: Session, key: str) -> Optional[str]:
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    return cfg.config_value if cfg else None


def _val(request_val: Optional[str], db: Session, db_key: str, default: str = "") -> str:
    """优先使用请求体里的值，其次数据库，最后用默认值"""
    if request_val is not None and request_val.strip():
        return request_val.strip()
    db_val = _get_config_value(db, db_key)
    if db_val and db_val.strip():
        return db_val.strip()
    return default


@router.get("/map-keys", summary="获取地图所需的真实 Key（不脱敏，已登录用户可访问）")
def get_map_keys(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user)
):
    """前端地图加载时调用，返回真实的高德 JS Key 和安全密钥"""
    js_key = _get_config_value(db, "amap_js_key") or ""
    security_code = _get_config_value(db, "amap_security_code") or ""
    return {"js_key": js_key, "security_code": security_code}


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
        llm_type = _val(body.llm_type, db, "llm.type", "local")

        if llm_type == "local":
            base_url = _val(body.llm_local_url, db, "llm.local_url", "http://localhost:11434/v1")
            api_key = "ollama"
            model = _val(body.llm_model_name, db, "llm.model_name", "qwen2.5:32b")
        else:
            base_url = _val(body.llm_api_base, db, "llm.api_base", "https://api.openai.com/v1")
            api_key = _val(body.llm_api_key, db, "llm.api_key", "")
            model = _val(body.llm_model_name, db, "llm.model_name", "gpt-4o-mini")

        logger.info(f"[LLM测试] type={llm_type}, url={base_url}, model={model}")

        # 方式一：尝试 /models 端点（OpenAI 兼容）
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("id", "") for m in data.get("data", [])]
                    model_list = ", ".join(models[:5]) if models else "（列表为空）"
                    return {"success": True, "message": f"连接成功！可用模型: {model_list}"}
                elif resp.status_code == 404:
                    # /models 不存在，尝试发一条简单对话
                    pass
                else:
                    return {"success": False, "message": f"服务响应异常 HTTP {resp.status_code}，请检查地址是否正确"}
        except httpx.ConnectError:
            return {"success": False, "message": f"无法连接到 {base_url}，请确认 Ollama 已启动且地址正确"}
        except httpx.TimeoutException:
            return {"success": False, "message": f"连接超时（8秒），请确认 Ollama 服务正常运行"}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

        # 方式二：/models 返回 404，尝试发一条最小 chat 请求
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1, "stream": False}
                )
                if resp.status_code == 200:
                    return {"success": True, "message": f"连接成功！模型 {model} 响应正常"}
                elif resp.status_code == 404:
                    return {"success": False, "message": f"模型 {model} 未找到，请确认模型已通过 ollama pull 下载"}
                else:
                    return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except httpx.ConnectError:
            return {"success": False, "message": f"无法连接到 {base_url}，请确认 Ollama 已启动"}
        except httpx.TimeoutException:
            return {"success": False, "message": f"模型响应超时，模型可能正在加载，请稍后再试"}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

    elif body.type == "embedding":
        embed_type = _val(body.embed_type, db, "embed.type", "local")
        model = _val(body.embed_model_name, db, "embed.model_name", "bge-m3:latest")

        if embed_type == "local":
            base_url = _val(body.embed_local_url, db, "embed.local_url", "http://localhost:11434/api/embeddings")
            logger.info(f"[Embed测试] type=local, url={base_url}, model={model}")
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(base_url, json={"model": model, "prompt": "测试连接"})
                    if resp.status_code == 200:
                        dim = len(resp.json().get("embedding", []))
                        return {"success": True, "message": f"连接成功！向量维度: {dim}"}
                    elif resp.status_code == 404:
                        return {"success": False, "message": f"模型 {model} 未找到，请执行 ollama pull {model}"}
                    else:
                        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            except httpx.ConnectError:
                return {"success": False, "message": f"无法连接到 {base_url}，请确认 Ollama 已启动"}
            except httpx.TimeoutException:
                return {"success": False, "message": "连接超时，模型可能正在加载"}
            except Exception as e:
                return {"success": False, "message": f"连接失败: {str(e)}"}
        else:
            base_url = _val(body.embed_local_url, db, "embed.api_base", "https://api.openai.com/v1")
            api_key = _val(body.embed_api_key, db, "embed.api_key", "")
            logger.info(f"[Embed测试] type=api, url={base_url}, model={model}")
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{base_url.rstrip('/')}/embeddings",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"model": model, "input": "测试连接"}
                    )
                    if resp.status_code == 200:
                        dim = len(resp.json().get("data", [{}])[0].get("embedding", []))
                        return {"success": True, "message": f"连接成功！向量维度: {dim}"}
                    else:
                        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"连接失败: {str(e)}"}

    elif body.type == "amap":
        api_key = _val(body.amap_api_key, db, "amap_api_key", "")
        if not api_key:
            return {"success": False, "message": "高德 API Key 未配置，请先在「地图 API」Tab 填写 Web 服务 Key"}
        logger.info(f"[高德测试] key={api_key[:8]}...")
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
