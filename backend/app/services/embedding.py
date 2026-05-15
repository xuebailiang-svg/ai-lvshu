"""
嵌入模型服务 (Embedding Service)
支持多种嵌入模型，通过配置动态切换：
- 本地 Ollama embeddings（bge-m3 等，推荐）
- OpenAI text-embedding-3-small / text-embedding-3-large
- 阿里云百炼 text-embedding-v3
- 自定义 OpenAI 兼容接口

配置 key 格式（与前端 SettingsView.vue 和 config.py 保持一致）：
  embed.type        = "local" | "api"
  embed.local_url   = "http://localhost:11434/api/embeddings"
  embed.model_name  = "bge-m3:latest"
  embed.api_base    = "https://api.openai.com/v1"
  embed.api_key     = "sk-..."
"""
import logging
import asyncio
import httpx
from typing import Optional
from sqlalchemy.orm import Session
from app.core.crypto import decrypt_config_value
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# 本地 sentence-transformers 模型缓存（避免重复加载）
_local_model_cache: dict = {}


def get_embedding_config(db: Session) -> dict:
    """
    从数据库读取嵌入模型配置
    使用 embed.* 格式 key，与前端保存的 key 完全一致
    """
    keys = [
        "embed.type",       # local | api
        "embed.api_key",    # API Key（本地不需要）
        "embed.api_base",   # 自定义 base_url（API 模式）
        "embed.local_url",  # 本地 Ollama embeddings URL
        "embed.model_name", # 模型名称
    ]
    configs = db.query(SystemConfig).filter(
        SystemConfig.config_key.in_(keys),
        SystemConfig.is_active == True
    ).all()
    cfg = {c.config_key: decrypt_config_value(c.config_value) for c in configs}

    embed_type = cfg.get("embed.type", "local")

    if embed_type == "local":
        provider = "ollama"
        base_url = cfg.get("embed.local_url") or "http://localhost:11434/api/embeddings"
        api_key = ""
    else:
        provider = "custom"
        base_url = cfg.get("embed.api_base") or ""
        api_key = cfg.get("embed.api_key") or ""

    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": cfg.get("embed.model_name") or "bge-m3:latest",
        "dimension": 1024,  # bge-m3 默认维度；API 模式由实际返回决定
        "embed_type": embed_type,
    }


async def embed_text(text: str, db: Session) -> list[float]:
    """
    将单条文本转换为向量
    返回 float 列表
    """
    cfg = get_embedding_config(db)
    provider = cfg["provider"]

    if provider == "ollama":
        return await _embed_ollama(text, cfg)
    else:
        return await _embed_api(text, cfg)


async def embed_texts(texts: list[str], db: Session) -> list[list[float]]:
    """批量文本向量化"""
    cfg = get_embedding_config(db)
    provider = cfg["provider"]

    if provider == "ollama":
        results = []
        for t in texts:
            vec = await _embed_ollama(t, cfg)
            results.append(vec)
        return results
    else:
        return await _embed_api_batch(texts, cfg)


async def _embed_ollama(text: str, cfg: dict) -> list[float]:
    """
    使用 Ollama 原生 embeddings 接口
    POST /api/embeddings  {"model": "...", "prompt": "..."}
    """
    url = cfg.get("base_url") or "http://localhost:11434/api/embeddings"
    model = cfg.get("model") or "bge-m3:latest"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"model": model, "prompt": text})
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding", [])
            if embedding:
                return [float(x) for x in embedding]
            logger.warning(f"Ollama embeddings 返回空向量，响应: {data}")
            return [0.0] * cfg["dimension"]
    except Exception as e:
        logger.error(f"Ollama embeddings 调用失败 ({url}): {e}")
        return [0.0] * cfg["dimension"]


async def _embed_api(text: str, cfg: dict) -> list[float]:
    """使用 OpenAI 兼容 API 嵌入模型"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("openai 包未安装，返回零向量")
        return [0.0] * cfg["dimension"]

    kwargs: dict = {"api_key": cfg["api_key"] or "none"}
    if cfg.get("base_url"):
        kwargs["base_url"] = cfg["base_url"]
    client = AsyncOpenAI(**kwargs)

    try:
        response = await client.embeddings.create(
            model=cfg["model"],
            input=text,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"API 嵌入失败: {e}")
        return [0.0] * cfg["dimension"]


async def _embed_api_batch(texts: list[str], cfg: dict) -> list[list[float]]:
    """批量 API 嵌入"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return [[0.0] * cfg["dimension"]] * len(texts)

    kwargs: dict = {"api_key": cfg["api_key"] or "none"}
    if cfg.get("base_url"):
        kwargs["base_url"] = cfg["base_url"]
    client = AsyncOpenAI(**kwargs)

    try:
        response = await client.embeddings.create(model=cfg["model"], input=texts)
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    except Exception as e:
        logger.error(f"批量 API 嵌入失败: {e}")
        return [[0.0] * cfg["dimension"]] * len(texts)


async def test_embedding_connection(db: Session) -> dict:
    """测试嵌入模型连通性"""
    cfg = get_embedding_config(db)
    try:
        vec = await embed_text("测试文本", db)
        non_zero = any(v != 0.0 for v in vec)
        return {
            "success": non_zero,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "dimension": len(vec),
            "sample": vec[:3],
            "message": "连接成功" if non_zero else "返回零向量，请检查模型是否已下载"
        }
    except Exception as e:
        return {"success": False, "provider": cfg["provider"], "error": str(e)}
