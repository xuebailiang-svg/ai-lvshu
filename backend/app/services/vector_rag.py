"""
向量 RAG 服务 (Vector RAG Service)
实现 Agentic RAG 的完整检索链路：
1. 文本向量化存储（历史案例、经验总结）
2. 混合搜索（向量相似度 + 全文检索）
3. 重排精选
4. 多跳检索（当第一跳结果触发关联查询时）

数据库：PostgreSQL + pgvector 扩展
"""
import logging
import json
from typing import Optional, AsyncGenerator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.embedding import embed_text
from app.services.reranker import rerank

logger = logging.getLogger(__name__)


# ===== 向量存储 =====

async def store_text_as_vector(
    content: str,
    metadata: dict,
    source_type: str,  # "store_experience" | "member_analysis" | "revenue_analysis"
    source_id: int,
    tenant_id: int,
    db: Session
) -> Optional[int]:
    """
    将文本向量化并存入 knowledge_vectors 表
    返回插入的 ID
    """
    try:
        embedding = await embed_text(content, db)
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"

        result = db.execute(text("""
            INSERT INTO knowledge_vectors
                (tenant_id, source_type, source_id, content, metadata, embedding, created_at)
            VALUES
                (:tenant_id, :source_type, :source_id, :content, :metadata, CAST(:embedding AS vector), NOW())
            ON CONFLICT (source_type, source_id)
            DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
        """), {
            "tenant_id": tenant_id,
            "source_type": source_type,
            "source_id": source_id,
            "content": content,
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "embedding": embedding_str,
        })
        db.commit()
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"向量存储失败: {e}")
        db.rollback()
        return None


async def ensure_vector_table(db: Session):
    """确保 knowledge_vectors 表和 pgvector 扩展存在"""
    try:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS knowledge_vectors (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                source_type VARCHAR(50) NOT NULL,
                source_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB DEFAULT '{}',
                embedding vector(1024),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP,
                UNIQUE(source_type, source_id)
            )
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_vectors_embedding
            ON knowledge_vectors USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_vectors_tenant
            ON knowledge_vectors (tenant_id, source_type)
        """))
        db.commit()
    except Exception as e:
        logger.warning(f"向量表初始化警告（可能已存在）: {e}")
        db.rollback()


# ===== 混合搜索 =====

async def hybrid_search(
    query: str,
    tenant_id: int,
    db: Session,
    source_types: Optional[list[str]] = None,
    top_k: int = 10,
    vector_weight: float = 0.7,
) -> list[dict]:
    """
    混合搜索：向量相似度（70%）+ 全文检索（30%）
    返回去重后的候选文档列表
    """
    results = {}

    # 1. 向量相似度搜索
    try:
        query_embedding = await embed_text(query, db)
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

        type_filter = ""
        params: dict = {
            "tenant_id": tenant_id,
            "embedding": embedding_str,
            "top_k": top_k
        }
        if source_types:
            type_filter = "AND source_type = ANY(:source_types)"
            params["source_types"] = source_types

        vector_results = db.execute(text(f"""
            SELECT id, source_type, source_id, content, metadata,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM knowledge_vectors
            WHERE tenant_id = :tenant_id {type_filter}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """), params).fetchall()

        for row in vector_results:
            results[row[0]] = {
                "id": row[0],
                "source_type": row[1],
                "source_id": row[2],
                "content": row[3],
                "metadata": row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}"),
                "vector_score": float(row[5]),
                "text_score": 0.0,
            }
    except Exception as e:
        logger.warning(f"向量搜索失败（可能未启用 pgvector）: {e}")

    # 2. 全文检索（PostgreSQL tsvector）
    try:
        type_filter = ""
        params2: dict = {"tenant_id": tenant_id, "query": query, "top_k": top_k}
        if source_types:
            type_filter = "AND source_type = ANY(:source_types)"
            params2["source_types"] = source_types

        text_results = db.execute(text(f"""
            SELECT id, source_type, source_id, content, metadata,
                   ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', :query)) AS rank
            FROM knowledge_vectors
            WHERE tenant_id = :tenant_id {type_filter}
              AND to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)
            ORDER BY rank DESC
            LIMIT :top_k
        """), params2).fetchall()

        for row in text_results:
            if row[0] in results:
                results[row[0]]["text_score"] = float(row[5])
            else:
                results[row[0]] = {
                    "id": row[0],
                    "source_type": row[1],
                    "source_id": row[2],
                    "content": row[3],
                    "metadata": row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}"),
                    "vector_score": 0.0,
                    "text_score": float(row[5]),
                }
    except Exception as e:
        logger.warning(f"全文检索失败: {e}")

    # 3. 融合评分
    candidates = list(results.values())
    for c in candidates:
        c["fusion_score"] = vector_weight * c["vector_score"] + (1 - vector_weight) * c["text_score"]

    candidates.sort(key=lambda x: x["fusion_score"], reverse=True)
    return candidates[:top_k]


# ===== Agentic RAG 主流程 =====

async def agentic_rag_retrieve(
    query: str,
    tenant_id: int,
    db: Session,
    top_k: int = 5,
    enable_multi_hop: bool = True,
) -> AsyncGenerator[dict, None]:
    """
    Agentic RAG 检索流程（带 SSE 日志输出）
    实现 5 个核心判断节点：
    1. 要不要检索
    2. 先检索哪一路
    3. 一次够不够（结果质量评估）
    4. 要不要多跳
    5. 怎么合并证据（重排 + 去重）
    """
    # 节点1：判断是否需要检索
    yield {"type": "thinking", "step": "意图分析", "message": f"分析查询意图：{query[:50]}..."}

    # 检查是否有历史向量数据
    count = db.execute(text(
        "SELECT COUNT(*) FROM knowledge_vectors WHERE tenant_id = :tid"
    ), {"tid": tenant_id}).scalar()

    if count == 0:
        yield {"type": "warning", "step": "知识库", "message": "历史知识库为空，跳过 RAG 检索，将基于规则评分"}
        return

    yield {"type": "result", "step": "意图分析", "message": f"知识库共 {count} 条历史记录，启动混合检索"}

    # 节点2：路由选择（并发多路检索）
    yield {"type": "executing", "step": "路由选择", "message": "启动混合检索：向量相似度(70%) + 全文检索(30%)"}

    candidates = await hybrid_search(query, tenant_id, db, top_k=top_k * 2)

    # 节点3：质量评估
    if not candidates:
        yield {"type": "warning", "step": "质量评估", "message": "第一轮检索无结果，尝试扩展查询..."}
        # 改写 query 重试
        expanded_query = query + " 电竞馆 选址 经验"
        candidates = await hybrid_search(expanded_query, tenant_id, db, top_k=top_k * 2)
        if candidates:
            yield {"type": "result", "step": "质量评估", "message": f"扩展查询后召回 {len(candidates)} 条结果"}
        else:
            yield {"type": "warning", "step": "质量评估", "message": "扩展查询仍无结果，跳过 RAG"}
            return
    else:
        yield {"type": "result", "step": "质量评估", "message": f"初步召回 {len(candidates)} 条候选，最高相似度 {candidates[0]['fusion_score']:.3f}"}

    # 节点4：多跳判断
    if enable_multi_hop and candidates:
        top_meta = candidates[0].get("metadata", {})
        store_name = top_meta.get("store_name", "")
        if store_name:
            yield {"type": "thinking", "step": "多跳检索", "message": f"发现关联店铺「{store_name}」，触发第二跳检索..."}
            second_hop = await hybrid_search(
                f"{store_name} 详细经验 成功因素",
                tenant_id, db, top_k=3
            )
            if second_hop:
                candidates.extend(second_hop)
                yield {"type": "result", "step": "多跳检索", "message": f"第二跳补充 {len(second_hop)} 条关联记录"}

    # 节点5：重排 + 去重
    yield {"type": "executing", "step": "重排精选", "message": f"对 {len(candidates)} 条候选进行重排..."}

    # 去重
    seen = set()
    unique_candidates = []
    for c in candidates:
        key = c["content"][:100]
        if key not in seen:
            seen.add(key)
            unique_candidates.append(c)

    # 重排
    doc_texts = [c["content"] for c in unique_candidates]
    reranked = await rerank(query, doc_texts, db, top_n=top_k)

    final_docs = []
    for r in reranked:
        original = unique_candidates[r["index"]]
        original["rerank_score"] = r["score"]
        final_docs.append(original)

    yield {
        "type": "result",
        "step": "重排完成",
        "message": f"精选 {len(final_docs)} 条高质量历史案例",
        "data": {"docs": final_docs}
    }
