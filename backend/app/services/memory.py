"""
记忆系统服务 (Memory System)
实现三类记忆，支持越用越聪明：

1. 语义记忆 (Semantic Memory)
   - 存储：电竞馆选址的通用知识、规律、评分标准
   - 来源：历史数据分析总结、用户确认的结论
   - 特点：长期稳定，不随时间衰减

2. 情景记忆 (Episodic Memory)
   - 存储：每次对话/评估的具体情境与结果
   - 来源：用户的每次评估请求和反馈
   - 特点：有时效性，使用艾宾浩斯遗忘曲线衰减权重

3. 程序记忆 (Procedural Memory)
   - 存储：用户的偏好、习惯、自定义规则
   - 来源：用户明确设定的偏好（如"偏重大学城选址"）
   - 特点：显式设定，优先级最高

记忆检索时，三类记忆综合注入 LLM 上下文
"""
import logging
import json
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.services.embedding import embed_text

logger = logging.getLogger(__name__)


# ===== 记忆表初始化 =====

async def ensure_memory_tables(db: Session):
    """确保记忆相关表存在"""
    try:
        # 语义记忆表
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS semantic_memories (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER,
                content TEXT NOT NULL,
                summary TEXT,
                embedding vector(384),
                confidence FLOAT DEFAULT 1.0,
                source VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP
            )
        """))

        # 情景记忆表（含遗忘曲线权重）
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS episodic_memories (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER,
                session_id VARCHAR(100),
                query TEXT NOT NULL,
                response_summary TEXT,
                address TEXT,
                score FLOAT,
                outcome VARCHAR(50),
                metadata JSONB DEFAULT '{}',
                embedding vector(384),
                access_count INTEGER DEFAULT 1,
                last_accessed TIMESTAMP DEFAULT NOW(),
                decay_weight FLOAT DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # 程序记忆表（用户偏好）
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS procedural_memories (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER,
                preference_key VARCHAR(100) NOT NULL,
                preference_value TEXT NOT NULL,
                description TEXT,
                priority INTEGER DEFAULT 5,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(tenant_id, user_id, preference_key)
            )
        """))

        # 对话会话表
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                session_id VARCHAR(100) UNIQUE NOT NULL,
                title VARCHAR(200),
                message_count INTEGER DEFAULT 0,
                last_message_at TIMESTAMP DEFAULT NOW(),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # 对话消息表
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(100) NOT NULL,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        db.commit()
    except Exception as e:
        logger.warning(f"记忆表初始化警告: {e}")
        db.rollback()


# ===== 情景记忆（遗忘曲线） =====

def calculate_decay_weight(last_accessed: datetime, access_count: int) -> float:
    """
    艾宾浩斯遗忘曲线权重计算
    R = e^(-t/S)，其中 t 为时间间隔（天），S 为记忆稳定性（与访问次数正相关）
    """
    import math
    days_elapsed = (datetime.now() - last_accessed).days
    stability = 1.0 + math.log(1 + access_count) * 2  # 访问越多，稳定性越高
    decay = math.exp(-days_elapsed / (stability * 10))  # 10 天基准衰减
    return max(0.1, min(1.0, decay))


async def save_episodic_memory(
    tenant_id: int,
    user_id: int,
    session_id: str,
    query: str,
    response_summary: str,
    address: Optional[str],
    score: Optional[float],
    db: Session,
    metadata: Optional[dict] = None,
):
    """保存情景记忆（异步，不阻塞主流程）"""
    try:
        embedding = await embed_text(query + " " + (response_summary[:200] if response_summary else ""), db)
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"

        db.execute(text("""
            INSERT INTO episodic_memories
                (tenant_id, user_id, session_id, query, response_summary, address, score, metadata, embedding, created_at)
            VALUES
                (:tenant_id, :user_id, :session_id, :query, :response_summary, :address, :score, :metadata, CAST(:embedding AS vector), NOW())
        """), {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "response_summary": response_summary[:500] if response_summary else "",
            "address": address,
            "score": score,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            "embedding": embedding_str,
        })
        db.commit()
    except Exception as e:
        logger.error(f"保存情景记忆失败: {e}")
        db.rollback()


async def retrieve_episodic_memories(
    query: str,
    tenant_id: int,
    user_id: int,
    db: Session,
    top_k: int = 3,
) -> list[dict]:
    """检索相关情景记忆（考虑遗忘曲线权重）"""
    try:
        embedding = await embed_text(query, db)
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"

        rows = db.execute(text("""
            SELECT id, query, response_summary, address, score, access_count, last_accessed, decay_weight,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM episodic_memories
            WHERE tenant_id = :tenant_id AND user_id = :user_id
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """), {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "embedding": embedding_str,
            "top_k": top_k * 3  # 多取一些，后续按综合分数过滤
        }).fetchall()

        memories = []
        for row in rows:
            # 重新计算遗忘曲线权重
            decay = calculate_decay_weight(row[6], row[5])
            combined_score = float(row[8]) * decay

            memories.append({
                "id": row[0],
                "query": row[1],
                "summary": row[2],
                "address": row[3],
                "score": row[4],
                "similarity": float(row[8]),
                "decay_weight": decay,
                "combined_score": combined_score,
            })

            # 更新访问记录（激活记忆）
            db.execute(text("""
                UPDATE episodic_memories
                SET access_count = access_count + 1,
                    last_accessed = NOW(),
                    decay_weight = :decay
                WHERE id = :id
            """), {"id": row[0], "decay": decay})

        db.commit()
        memories.sort(key=lambda x: x["combined_score"], reverse=True)
        return memories[:top_k]

    except Exception as e:
        logger.warning(f"检索情景记忆失败: {e}")
        return []


# ===== 语义记忆 =====

async def save_semantic_memory(
    tenant_id: int,
    content: str,
    summary: str,
    source: str,
    db: Session,
    user_id: Optional[int] = None,
    confidence: float = 1.0,
):
    """保存语义记忆（通用知识）"""
    try:
        embedding = await embed_text(content, db)
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"

        db.execute(text("""
            INSERT INTO semantic_memories
                (tenant_id, user_id, content, summary, embedding, confidence, source, created_at)
            VALUES
                (:tenant_id, :user_id, :content, :summary, CAST(:embedding AS vector), :confidence, :source, NOW())
        """), {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "content": content,
            "summary": summary,
            "embedding": embedding_str,
            "confidence": confidence,
            "source": source,
        })
        db.commit()
    except Exception as e:
        logger.error(f"保存语义记忆失败: {e}")
        db.rollback()


async def retrieve_semantic_memories(
    query: str,
    tenant_id: int,
    db: Session,
    top_k: int = 3,
) -> list[dict]:
    """检索相关语义记忆"""
    try:
        embedding = await embed_text(query, db)
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"

        rows = db.execute(text("""
            SELECT id, content, summary, confidence, source,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM semantic_memories
            WHERE tenant_id = :tenant_id
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """), {"tenant_id": tenant_id, "embedding": embedding_str, "top_k": top_k}).fetchall()

        return [
            {"id": r[0], "content": r[1], "summary": r[2], "confidence": r[3], "source": r[4], "similarity": float(r[5])}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"检索语义记忆失败: {e}")
        return []


# ===== 程序记忆（用户偏好） =====

def get_procedural_memories(tenant_id: int, user_id: int, db: Session) -> list[dict]:
    """获取用户程序记忆（偏好设置）"""
    try:
        rows = db.execute(text("""
            SELECT preference_key, preference_value, description, priority
            FROM procedural_memories
            WHERE tenant_id = :tenant_id AND user_id = :user_id AND is_active = TRUE
            ORDER BY priority DESC
        """), {"tenant_id": tenant_id, "user_id": user_id}).fetchall()

        return [{"key": r[0], "value": r[1], "description": r[2], "priority": r[3]} for r in rows]
    except Exception as e:
        logger.warning(f"获取程序记忆失败: {e}")
        return []


def save_procedural_memory(
    tenant_id: int,
    user_id: int,
    preference_key: str,
    preference_value: str,
    description: str,
    db: Session,
    priority: int = 5,
):
    """保存/更新程序记忆"""
    try:
        db.execute(text("""
            INSERT INTO procedural_memories
                (tenant_id, user_id, preference_key, preference_value, description, priority)
            VALUES
                (:tenant_id, :user_id, :key, :value, :description, :priority)
            ON CONFLICT (tenant_id, user_id, preference_key)
            DO UPDATE SET
                preference_value = EXCLUDED.preference_value,
                description = EXCLUDED.description,
                priority = EXCLUDED.priority
        """), {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "key": preference_key,
            "value": preference_value,
            "description": description,
            "priority": priority,
        })
        db.commit()
    except Exception as e:
        logger.error(f"保存程序记忆失败: {e}")
        db.rollback()


# ===== 综合记忆上下文构建 =====

async def build_memory_context(
    query: str,
    tenant_id: int,
    user_id: int,
    db: Session,
) -> str:
    """
    综合三类记忆，构建注入 LLM 的上下文字符串
    优先级：程序记忆 > 语义记忆 > 情景记忆
    """
    context_parts = []

    # 1. 程序记忆（用户偏好，最高优先级）
    procedural = get_procedural_memories(tenant_id, user_id, db)
    if procedural:
        prefs = "\n".join([f"- {p['description'] or p['key']}: {p['value']}" for p in procedural])
        context_parts.append(f"【用户偏好设置】\n{prefs}")

    # 2. 语义记忆（通用知识）
    semantic = await retrieve_semantic_memories(query, tenant_id, db, top_k=2)
    if semantic:
        knowledge = "\n".join([f"- {m['summary'] or m['content'][:100]}" for m in semantic])
        context_parts.append(f"【相关选址知识】\n{knowledge}")

    # 3. 情景记忆（历史对话，遗忘曲线加权）
    episodic = await retrieve_episodic_memories(query, tenant_id, user_id, db, top_k=2)
    if episodic:
        history = "\n".join([
            f"- 曾评估「{m['address'] or '未知地址'}」得分 {m['score'] or '-'}，{m['summary'] or ''}"
            for m in episodic
        ])
        context_parts.append(f"【历史评估记忆】\n{history}")

    if not context_parts:
        return ""

    return "\n\n".join(context_parts)


# ===== 对话历史管理 =====

def save_chat_message(
    session_id: str,
    tenant_id: int,
    user_id: int,
    role: str,
    content: str,
    db: Session,
    metadata: Optional[dict] = None,
):
    """保存对话消息"""
    try:
        db.execute(text("""
            INSERT INTO chat_messages (session_id, tenant_id, user_id, role, content, metadata, created_at)
            VALUES (:session_id, :tenant_id, :user_id, :role, :content, :metadata, NOW())
        """), {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
        })
        db.execute(text("""
            UPDATE chat_sessions
            SET message_count = message_count + 1, last_message_at = NOW()
            WHERE session_id = :session_id
        """), {"session_id": session_id})
        db.commit()
    except Exception as e:
        logger.error(f"保存对话消息失败: {e}")
        db.rollback()


def get_chat_history(session_id: str, db: Session, limit: int = 20) -> list[dict]:
    """获取对话历史（最近 N 条）"""
    try:
        rows = db.execute(text("""
            SELECT role, content, created_at
            FROM chat_messages
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"session_id": session_id, "limit": limit}).fetchall()

        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    except Exception as e:
        logger.warning(f"获取对话历史失败: {e}")
        return []
