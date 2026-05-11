"""
重排模型服务 (Reranker Service)
用于多路召回后的精排，提升 Context Precision
支持：
- 本地 BGE-Reranker (BAAI/bge-reranker-v2-m3)
- Cohere Rerank API
- 自定义 HTTP 重排接口
- 无重排（直接按原始分数返回，降级方案）
"""
import logging
import asyncio
from typing import Optional
from sqlalchemy.orm import Session
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

_reranker_model_cache: dict = {}


def get_reranker_config(db: Session) -> dict:
    """
    从数据库读取重排模型配置
    使用 rerank.* 格式 key，与前端 SettingsView.vue 和 config.py 保存的 key 完全一致
    """
    keys = [
        "rerank.type",       # local | api | none
        "rerank.api_key",
        "rerank.local_url",  # 本地 Ollama reranker URL
        "rerank.model_name", # 模型名称
    ]
    configs = db.query(SystemConfig).filter(
        SystemConfig.config_key.in_(keys),
        SystemConfig.is_active == True
    ).all()
    cfg = {c.config_key: c.config_value for c in configs}

    rerank_type = cfg.get("rerank.type", "none")
    if rerank_type == "local":
        provider = "local"
        base_url = cfg.get("rerank.local_url", "")
        api_key = ""
    elif rerank_type == "api":
        provider = "custom"
        base_url = ""
        api_key = cfg.get("rerank.api_key", "")
    else:
        provider = "none"
        base_url = ""
        api_key = ""

    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": cfg.get("rerank.model_name") or "BAAI/bge-reranker-v2-m3",
        "top_n": 5,
    }


async def rerank(
    query: str,
    documents: list[str],
    db: Session,
    top_n: Optional[int] = None,
) -> list[dict]:
    """
    对文档列表进行重排
    返回 [{"index": int, "text": str, "score": float}]，按相关性降序排列
    """
    if not documents:
        return []

    cfg = get_reranker_config(db)
    n = top_n or cfg["top_n"]
    provider = cfg["provider"]

    if provider == "local":
        return await _rerank_local(query, documents, cfg["model"], n)
    elif provider == "cohere":
        return await _rerank_cohere(query, documents, cfg, n)
    elif provider == "custom":
        return await _rerank_custom(query, documents, cfg, n)
    else:
        # 无重排：直接返回原始顺序（降级方案）
        return [
            {"index": i, "text": doc, "score": 1.0 - i * 0.01}
            for i, doc in enumerate(documents[:n])
        ]


async def _rerank_local(query: str, documents: list[str], model_name: str, top_n: int) -> list[dict]:
    """使用本地 BGE-Reranker 重排"""
    global _reranker_model_cache

    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        logger.warning("sentence-transformers 未安装，跳过重排")
        return [{"index": i, "text": doc, "score": 1.0} for i, doc in enumerate(documents[:top_n])]

    if model_name not in _reranker_model_cache:
        logger.info(f"加载本地重排模型: {model_name}")
        loop = asyncio.get_event_loop()
        model = await loop.run_in_executor(None, CrossEncoder, model_name)
        _reranker_model_cache[model_name] = model

    model = _reranker_model_cache[model_name]
    pairs = [(query, doc) for doc in documents]

    loop = asyncio.get_event_loop()
    scores = await loop.run_in_executor(None, model.predict, pairs)

    ranked = sorted(
        [{"index": i, "text": documents[i], "score": float(scores[i])} for i in range(len(documents))],
        key=lambda x: x["score"],
        reverse=True
    )
    return ranked[:top_n]


async def _rerank_cohere(query: str, documents: list[str], cfg: dict, top_n: int) -> list[dict]:
    """使用 Cohere Rerank API"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.cohere.ai/v1/rerank",
                headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                json={
                    "model": cfg.get("model", "rerank-multilingual-v3.0"),
                    "query": query,
                    "documents": documents,
                    "top_n": top_n,
                }
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"index": r["index"], "text": documents[r["index"]], "score": r["relevance_score"]}
                for r in data["results"]
            ]
    except Exception as e:
        logger.error(f"Cohere Rerank 失败: {e}")
        return [{"index": i, "text": doc, "score": 1.0} for i, doc in enumerate(documents[:top_n])]


async def _rerank_custom(query: str, documents: list[str], cfg: dict, top_n: int) -> list[dict]:
    """使用自定义 HTTP 重排接口（OpenAI 兼容格式）"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{cfg['base_url']}/rerank",
                headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                json={"model": cfg["model"], "query": query, "documents": documents, "top_n": top_n}
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"index": r["index"], "text": documents[r["index"]], "score": r["relevance_score"]}
                for r in data["results"]
            ]
    except Exception as e:
        logger.error(f"自定义重排接口失败: {e}")
        return [{"index": i, "text": doc, "score": 1.0} for i, doc in enumerate(documents[:top_n])]
