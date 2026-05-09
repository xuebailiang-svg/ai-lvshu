"""
嵌入模型服务 (Embedding Service)
支持多种嵌入模型，通过配置动态切换：
- 本地 sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2 等)
- OpenAI text-embedding-3-small / text-embedding-3-large
- 阿里云百炼 text-embedding-v3
- 自定义 OpenAI 兼容接口

向量维度：本地模型 384/768，OpenAI 1536/3072
"""
import logging
import asyncio
from typing import Optional
from sqlalchemy.orm import Session
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# 本地模型缓存（避免重复加载）
_local_model_cache: dict = {}


def get_embedding_config(db: Session) -> dict:
    """从数据库读取嵌入模型配置"""
    keys = [
        "embedding_provider",   # local | openai | aliyun | custom
        "embedding_api_key",    # API Key（本地不需要）
        "embedding_base_url",   # 自定义 base_url
        "embedding_model",      # 模型名称
        "embedding_dimension",  # 向量维度
    ]
    configs = db.query(SystemConfig).filter(
        SystemConfig.config_key.in_(keys),
        SystemConfig.is_active == True
    ).all()
    cfg = {c.config_key: c.config_value for c in configs}

    return {
        "provider": cfg.get("embedding_provider", "local"),
        "api_key": cfg.get("embedding_api_key", ""),
        "base_url": cfg.get("embedding_base_url", ""),
        "model": cfg.get("embedding_model", "paraphrase-multilingual-MiniLM-L12-v2"),
        "dimension": int(cfg.get("embedding_dimension", "384")),
    }


async def embed_text(text: str, db: Session) -> list[float]:
    """
    将单条文本转换为向量
    返回 float 列表
    """
    cfg = get_embedding_config(db)
    provider = cfg["provider"]

    if provider == "local":
        return await _embed_local(text, cfg["model"])
    else:
        return await _embed_api(text, cfg)


async def embed_texts(texts: list[str], db: Session) -> list[list[float]]:
    """批量文本向量化"""
    cfg = get_embedding_config(db)
    provider = cfg["provider"]

    if provider == "local":
        results = []
        for text in texts:
            vec = await _embed_local(text, cfg["model"])
            results.append(vec)
        return results
    else:
        return await _embed_api_batch(texts, cfg)


async def _embed_local(text: str, model_name: str) -> list[float]:
    """使用本地 sentence-transformers 模型"""
    global _local_model_cache

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning("sentence-transformers 未安装，返回零向量")
        return [0.0] * 384

    if model_name not in _local_model_cache:
        logger.info(f"加载本地嵌入模型: {model_name}")
        # 在线程池中加载模型（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        model = await loop.run_in_executor(None, SentenceTransformer, model_name)
        _local_model_cache[model_name] = model

    model = _local_model_cache[model_name]
    loop = asyncio.get_event_loop()
    embedding = await loop.run_in_executor(None, model.encode, text)
    return embedding.tolist()


async def _embed_api(text: str, cfg: dict) -> list[float]:
    """使用 API 嵌入模型（OpenAI 兼容接口）"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("openai 包未安装，返回零向量")
        return [0.0] * cfg["dimension"]

    provider = cfg["provider"]
    if provider == "aliyun":
        base_url = cfg.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=base_url)
    elif provider == "custom":
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    else:
        client = AsyncOpenAI(api_key=cfg["api_key"])

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

    provider = cfg["provider"]
    if provider == "aliyun":
        base_url = cfg.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=base_url)
    elif provider == "custom":
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    else:
        client = AsyncOpenAI(api_key=cfg["api_key"])

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
        return {
            "success": True,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "dimension": len(vec),
            "sample": vec[:3]
        }
    except Exception as e:
        return {"success": False, "provider": cfg["provider"], "error": str(e)}
