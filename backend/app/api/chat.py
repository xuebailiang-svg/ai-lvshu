"""
对话评估 API (Chat API)
整合 LLM + Agentic RAG + 三类记忆系统
支持 SSE 流式输出（含工作流日志 + LLM 生成过程 + 推荐问题）

端点：
- POST /api/v1/chat/message       - 发送消息（SSE 流式）
- GET  /api/v1/chat/sessions      - 获取会话列表
- POST /api/v1/chat/sessions      - 创建新会话
- GET  /api/v1/chat/sessions/{id}/messages - 获取会话消息历史
- GET  /api/v1/chat/memory/preferences     - 获取用户偏好（程序记忆）
- POST /api/v1/chat/memory/preferences     - 设置用户偏好
"""
import json
import uuid
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.db.session import SessionLocal
from app.models.user import User
from app.services.llm_gateway import chat_completion_stream, chat_completion
from app.services.vector_rag import agentic_rag_retrieve
from app.services.memory import (
    build_memory_context,
    save_episodic_memory,
    save_chat_message,
    get_chat_history,
    get_procedural_memories,
    save_procedural_memory,
    ensure_memory_tables,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["对话评估"])

SYSTEM_PROMPT = """你是一位专业的电竞馆选址顾问，拥有丰富的电竞行业经验和数据分析能力。

你的职责：
1. 根据用户提供的地址或区域，结合评分数据和历史案例，给出专业的选址建议
2. 深度分析周边竞品、目标客群（18-30岁年轻人）、交通便利性、配套设施等关键因素
3. 结合历史成功/失败案例，提供有数据支撑的判断
4. 语言专业清晰，使用 Markdown 格式组织回答（标题、加粗、列表），让报告结构清晰

回答格式要求：
- 使用 ## 作为主要章节标题
- 使用 **加粗** 强调关键数据和结论
- 使用列表（- 或 1.）组织多条建议
- 重要数字用表格对比展示

注意事项：
- 如果有历史数据支撑，请明确引用（如"根据您在XX的门店经验..."）
- 如果数据不足，请诚实说明，并给出基于行业经验的建议
- 始终关注电竞馆的核心客群：18-30岁年轻人，尤其是大学生和年轻白领
"""

SUGGEST_SYSTEM_PROMPT = """你是一个智能问题推荐助手。根据对话内容，生成3个用户可能感兴趣的追问问题。
要求：
- 问题要具体、有针对性，与选址场景相关
- 每个问题不超过25个字
- 必须严格返回 JSON 数组格式，不要有任何其他内容
示例：["这个地址的竞品情况如何？", "附近有哪些大学？", "建议的最佳开业时间是？"]
"""


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    address: Optional[str] = None  # 如果是地址评估，传入地址


class PreferenceRequest(BaseModel):
    key: str
    value: str
    description: str
    priority: int = 5


@router.post("/message")
async def chat_message(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    发送消息（SSE 流式输出）
    输出格式：
    - type=log: 工作流日志（Agent 思考过程）
    - type=token: LLM 生成的 token（流式文本）
    - type=suggestions: 推荐追问问题列表（回复完成后推送）
    - type=done: 完成信号
    """
    # 确保记忆表存在
    await ensure_memory_tables(db)

    # 创建或获取会话
    session_id = req.session_id or str(uuid.uuid4())
    _ensure_session(session_id, current_user, db)

    # ★ 关键修复：提前提取 user 的所有属性值（普通 int/str），避免在 StreamingResponse 中
    # 访问 SQLAlchemy ORM 对象时触发 lazy load，导致 "not bound to a Session" 错误
    user_id = current_user.id
    tenant_id = current_user.tenant_id
    message_text = req.message
    address = req.address

    async def event_stream():
        # event_stream 内部使用独立的 db Session，不依赖已关闭的外部 db
        stream_db = SessionLocal()
        full_response = ""
        try:
            # 1. 保存用户消息
            save_chat_message(session_id, tenant_id, user_id, "user", message_text, stream_db)

            # 2. 获取对话历史
            history = get_chat_history(session_id, stream_db, limit=10)

            # 3. 工作流日志：记忆检索
            yield _log_event("thinking", "记忆检索", "正在检索历史记忆和用户偏好...")

            memory_context = await build_memory_context(
                message_text, tenant_id, user_id, stream_db
            )
            if memory_context:
                yield _log_event("result", "记忆注入", f"已注入 {len(memory_context)} 字符的记忆上下文")
            else:
                yield _log_event("warning", "记忆检索", "暂无历史记忆，将基于当前信息回答")

            # 4. Agentic RAG 检索
            rag_docs = []
            async for rag_step in agentic_rag_retrieve(
                message_text, tenant_id, stream_db
            ):
                yield _log_event(rag_step["type"], rag_step["step"], rag_step["message"])
                if rag_step.get("data", {}).get("docs"):
                    rag_docs = rag_step["data"]["docs"]

            # 5. 构建 LLM 消息列表
            messages = _build_messages(
                user_message=message_text,
                history=history,
                memory_context=memory_context,
                rag_docs=rag_docs,
                address=address,
            )

            # 6. 流式生成回复
            yield _log_event("executing", "生成报告", f"调用大模型生成分析报告（共 {len(messages)} 条上下文）...")

            async for token in chat_completion_stream(messages, stream_db, system_prompt=SYSTEM_PROMPT):
                full_response += token
                yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            # 7. 保存助手回复
            save_chat_message(session_id, tenant_id, user_id, "assistant", full_response, stream_db)

            # 8. 生成推荐追问问题（非流式，快速调用）
            try:
                suggest_messages = _build_suggest_messages(message_text, full_response, history)
                suggestions_raw = await chat_completion(
                    suggest_messages, stream_db, system_prompt=SUGGEST_SYSTEM_PROMPT
                )
                suggestions = _parse_suggestions(suggestions_raw)
                if suggestions:
                    yield f"data: {json.dumps({'type': 'suggestions', 'questions': suggestions}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.warning(f"推荐问题生成失败（不影响主流程）: {e}")

            # 9. 异步保存情景记忆（不阻塞响应）
            asyncio.create_task(save_episodic_memory(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                query=message_text,
                response_summary=full_response[:300],
                address=address,
                score=None,
                db=stream_db,
            ))

            yield _log_event("final", "完成", "回复生成完毕，已保存到对话历史")
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"对话处理异常: {e}", exc_info=True)
            yield _log_event("error", "系统错误", str(e)[:200])
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/sessions")
async def get_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取当前用户的会话列表"""
    await ensure_memory_tables(db)
    rows = db.execute(text("""
        SELECT session_id, title, message_count, last_message_at, created_at
        FROM chat_sessions
        WHERE tenant_id = :tenant_id AND user_id = :user_id
        ORDER BY last_message_at DESC
        LIMIT 50
    """), {"tenant_id": current_user.tenant_id, "user_id": current_user.id}).fetchall()

    return [
        {
            "session_id": r[0],
            "title": r[1] or "新对话",
            "message_count": r[2],
            "last_message_at": r[3].isoformat() if r[3] else None,
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


@router.post("/sessions")
async def create_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建新会话"""
    await ensure_memory_tables(db)
    session_id = str(uuid.uuid4())
    _ensure_session(session_id, current_user, db)
    return {"session_id": session_id}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取会话消息历史"""
    rows = db.execute(text("""
        SELECT role, content, created_at
        FROM chat_messages
        WHERE session_id = :session_id AND tenant_id = :tenant_id
        ORDER BY created_at ASC
    """), {"session_id": session_id, "tenant_id": current_user.tenant_id}).fetchall()

    return [
        {"role": r[0], "content": r[1], "created_at": r[2].isoformat() if r[2] else None}
        for r in rows
    ]


@router.get("/memory/preferences")
async def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取用户偏好（程序记忆）"""
    await ensure_memory_tables(db)
    return get_procedural_memories(current_user.tenant_id, current_user.id, db)


@router.post("/memory/preferences")
async def set_preference(
    req: PreferenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """设置用户偏好（程序记忆）"""
    await ensure_memory_tables(db)
    save_procedural_memory(
        current_user.tenant_id, current_user.id,
        req.key, req.value, req.description, db, req.priority
    )
    return {"success": True, "message": f"偏好「{req.key}」已保存"}


# ===== 工具函数 =====

def _log_event(event_type: str, step: str, message: str) -> str:
    data = json.dumps({"type": "log", "log_type": event_type, "step": step, "message": message}, ensure_ascii=False)
    return f"data: {data}\n\n"


def _ensure_session(session_id: str, user: User, db: Session):
    """确保会话记录存在"""
    try:
        db.execute(text("""
            INSERT INTO chat_sessions (session_id, tenant_id, user_id, created_at, last_message_at)
            VALUES (:session_id, :tenant_id, :user_id, NOW(), NOW())
            ON CONFLICT (session_id) DO NOTHING
        """), {"session_id": session_id, "tenant_id": user.tenant_id, "user_id": user.id})
        db.commit()
    except Exception:
        db.rollback()


def _build_messages(
    user_message: str,
    history: list[dict],
    memory_context: str,
    rag_docs: list[dict],
    address: Optional[str],
) -> list[dict]:
    """构建发送给 LLM 的消息列表"""
    messages = []

    # 注入记忆上下文（作为系统补充）
    if memory_context:
        messages.append({
            "role": "system",
            "content": f"以下是用户的历史记忆和偏好，请在回答时参考：\n\n{memory_context}"
        })

    # 注入 RAG 检索结果
    if rag_docs:
        rag_context = "\n\n".join([
            f"【历史案例 {i+1}】{doc['content'][:300]}"
            for i, doc in enumerate(rag_docs[:3])
        ])
        messages.append({
            "role": "system",
            "content": f"以下是从历史数据库中检索到的相关案例，请在分析时引用：\n\n{rag_context}"
        })

    # 对话历史（最近 6 轮）
    for msg in history[-12:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # 当前用户消息
    current_content = user_message
    if address:
        current_content = f"请评估以下地址：{address}\n\n{user_message}"

    messages.append({"role": "user", "content": current_content})
    return messages


def _build_suggest_messages(
    user_message: str,
    assistant_response: str,
    history: list[dict],
) -> list[dict]:
    """构建推荐问题生成的消息列表"""
    recent = history[-4:] if len(history) > 4 else history
    context_parts = []
    for msg in recent:
        role_label = "用户" if msg["role"] == "user" else "助手"
        context_parts.append(f"{role_label}：{msg['content'][:100]}\n")
    context_parts.append(f"用户：{user_message}\n")
    context_parts.append(f"助手：{assistant_response[:200]}\n")
    return [
        {
            "role": "user",
            "content": f"以下是对话内容：\n\n{''.join(context_parts)}\n请生成3个用户可能感兴趣的追问问题，JSON数组格式。"
        }
    ]


def _parse_suggestions(raw: str) -> list[str]:
    """解析 LLM 返回的推荐问题 JSON"""
    if not raw:
        return []
    try:
        result = json.loads(raw.strip())
        if isinstance(result, list):
            return [str(q) for q in result[:3] if q]
    except Exception:
        pass
    import re
    match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(q) for q in result[:3] if q]
        except Exception:
            pass
    lines = [l.strip().lstrip('0123456789.-、。 ').strip('"\'') for l in raw.strip().split('\n') if l.strip()]
    lines = [l for l in lines if 5 < len(l) < 50]
    return lines[:3]
