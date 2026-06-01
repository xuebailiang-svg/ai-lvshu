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
1. 作为 AI 选址顾问，优先解读已生成的正式评估报告和用户追问
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
- 如果上下文中没有正式评估数据，只能提供通用分析思路和需补充数据清单，不得输出确定性评分、评级或正式选址结论
- 如果上下文中没有真实评估数据，或数据来源包含模拟/估算，必须在结论前明确标注“数据不足/包含模拟数据”，不得把模拟数据描述成真实调研结果
- 生成正式选址建议前，优先提醒用户补充租金、面积、政策/消防/证照限制等客户侧真实数据
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
    evaluation_context: Optional[dict] = None  # 当前评估结果（分数、各维度数据），由前端传入


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
    evaluation_context = req.evaluation_context  # 当前评估结果上下文

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

            if _requires_live_map_data(message_text, address, evaluation_context):
                full_response = _build_live_map_required_response(address)
                yield _log_event("warning", "真实地图数据", "当前问题需要实时高德地图 API，但 AI 选址顾问未关联正式评估报告")
                yield f"data: {json.dumps({'type': 'token', 'content': full_response}, ensure_ascii=False)}\n\n"
                save_chat_message(session_id, tenant_id, user_id, "assistant", full_response, stream_db)
                yield f"data: {json.dumps({'type': 'suggestions', 'questions': ['去新地址评估生成报告', '如何补齐租金和政策数据？', '生成报告后怎样继续追问？']}, ensure_ascii=False)}\n\n"
                yield _log_event("final", "完成", "已阻止无真实地图数据的自由回答")
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
                return

            # 4. 判断是否需要 Agentic RAG 检索
            rag_docs = []
            should_search_rag, rag_reason = _should_search_rag(
                message_text,
                address=address,
                evaluation_context=evaluation_context,
            )
            yield _log_event("thinking", "知识库判断", rag_reason)
            if should_search_rag:
                try:
                    async for rag_step in agentic_rag_retrieve(
                        message_text, tenant_id, stream_db
                    ):
                        yield _log_event(rag_step["type"], rag_step["step"], rag_step["message"])
                        if rag_step.get("data", {}).get("docs"):
                            rag_docs = rag_step["data"]["docs"]
                except Exception as e:
                    logger.warning(f"RAG 知识库检索失败，继续生成回答: {e}", exc_info=True)
                    yield _log_event("warning", "知识库检索", "知识库暂不可用，将基于当前上下文继续回答")
            else:
                yield _log_event("result", "知识库判断", "当前问题属于系统操作或通用说明，跳过 RAG 知识库检索")

            # 5. 构建 LLM 消息列表
            messages = _build_messages(
                user_message=message_text,
                history=history,
                memory_context=memory_context,
                rag_docs=rag_docs,
                address=address,
                evaluation_context=evaluation_context,
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

            # 9. 保存情景记忆（同步 await，避免 stream_db 在 finally 关闭后 task 仍在使用 db 的竞态条件）
            try:
                await save_episodic_memory(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    query=message_text,
                    response_summary=full_response[:300],
                    address=address,
                    score=None,
                    db=stream_db,
                )
            except Exception as e:
                logger.warning(f"情景记忆保存失败（不影响主流程）: {e}")

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


def _should_search_rag(
    message: str,
    address: Optional[str] = None,
    evaluation_context: Optional[dict] = None,
) -> tuple[bool, str]:
    """判断当前聊天问题是否需要检索 RAG 知识库。"""
    if address:
        return True, "本轮问题带有候选地址，需要检索历史经验和相似案例"
    if evaluation_context:
        return True, "本轮问题带有评估上下文，需要检索历史经验辅助解释"

    text = (message or "").strip().lower()
    if not text:
        return False, "问题为空，跳过 RAG 知识库检索"

    operation_keywords = [
        "怎么上传", "如何上传", "上传模板", "模板怎么", "模板", "配置", "密钥", "key",
        "登录", "密码", "部署", "github", "git", "报错", "错误", "按钮", "页面",
        "账号", "连接", "打包", "安装", "启动", "重启", "端口",
    ]
    rag_core_keywords = [
        "选址", "地址", "商圈", "门店", "历史", "案例", "经验", "复盘",
        "适不适合", "适合", "不适合", "推荐", "不推荐", "竞品", "客群",
        "租金", "交通", "消费", "成功", "失败", "报告", "相似",
    ]
    rag_weak_keywords = ["权重", "评分", "因素", "画像", "营收", "客流"]

    operation_hits = [kw for kw in operation_keywords if kw in text]
    core_hits = [kw for kw in rag_core_keywords if kw in text]
    weak_hits = [kw for kw in rag_weak_keywords if kw in text]

    if operation_hits and not core_hits:
        return False, f"识别为系统操作/配置问题（命中：{operation_hits[0]}），跳过 RAG 知识库检索"

    if core_hits:
        return True, f"问题涉及选址经验、历史案例或报告分析（命中：{core_hits[0]}），需要检索 RAG 知识库"

    if weak_hits and not operation_hits:
        return True, f"问题涉及评分数据或经营因素（命中：{weak_hits[0]}），需要检索 RAG 知识库"

    return False, "未识别到历史经验、案例或选址判断意图，跳过 RAG 知识库检索"


def _requires_live_map_data(
    message: str,
    address: Optional[str],
    evaluation_context: Optional[dict],
) -> bool:
    if evaluation_context:
        return False
    text = (message or "").lower()
    has_address_context = bool(address) or any(token in text for token in ["省", "市", "区", "县", "街", "路", "号", "商业中心", "商圈"])
    if not has_address_context:
        return False
    map_data_keywords = [
        "真实数据", "真实api", "高德", "地图", "周边", "附近", "多少", "几个", "几所",
        "学校", "小学", "中学", "大学", "高校", "竞品", "网吧", "电竞馆", "距离",
        "列出", "分别", "名称", "类型", "poi",
    ]
    return any(keyword in text for keyword in map_data_keywords)


def _build_live_map_required_response(address: Optional[str]) -> str:
    address_text = f"「{address}」" if address else "这个地址"
    return f"""## 需要先生成正式评估报告

你问的是 {address_text} 周边学校、类型、距离等**实时地图数据**。这类问题不能由 AI 选址顾问直接凭空回答，也不能用模拟数据替代。

请先进入 **新地址评估**：

1. 输入或地图选点该地址
2. 确认已配置并测试通过高德地图 API
3. 补充租金、面积、政策/消防/证照等客户侧真实数据
4. 生成正式报告后，再点击 **继续追问 / 解读报告**

正式评估报告会调用统一评估引擎，使用高德地理编码和周边 POI 查询；AI 选址顾问只负责基于已生成报告继续解释和追问。"""


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


def _format_report_pois(title: str, pois: list[dict], limit: int = 12) -> str:
    if not pois:
        return f"{title}：无"
    lines = [f"{title}："]
    for poi in pois[:limit]:
        name = poi.get("name") or "未命名 POI"
        distance = poi.get("distance")
        distance_text = f"{distance}m" if isinstance(distance, int) else "距离未知"
        label = poi.get("classification_label") or poi.get("classification") or poi.get("type") or "未分类"
        reason = poi.get("classification_reason") or ""
        lines.append(f"- {name}，{label}，{distance_text}，{reason}")
    return "\n".join(lines)


def _build_evaluation_evidence_context(ctx: dict) -> str:
    population = (ctx.get("dimensions") or {}).get("population") or {}
    if not population:
        return ""

    evidence_parts = []
    summary = population.get("education_filter_summary")
    if summary:
        evidence_parts.append(f"教育 POI 清洗摘要：{summary}")

    counts = [
        ("高德原始匹配", population.get("education_raw_match_count") or population.get("university_api_total_count")),
        ("有效教育客群", population.get("education_effective_count")),
        ("高校/高职", population.get("higher_education_count") or population.get("university_count")),
        ("初高中/中职", population.get("secondary_education_count")),
        ("待核验学校", population.get("education_candidate_count")),
        ("已排除误匹配", population.get("excluded_education_count")),
    ]
    count_text = "，".join([f"{name} {value}" for name, value in counts if isinstance(value, int)])
    if count_text:
        evidence_parts.append(f"教育 POI 数量：{count_text}")

    evidence_parts.append(_format_report_pois("计入评分/客群分析的学校", population.get("education_pois") or population.get("university_pois") or []))
    evidence_parts.append(_format_report_pois("其中高校/高职", population.get("higher_education_pois") or population.get("university_pois") or []))
    evidence_parts.append(_format_report_pois("其中初高中/中职", population.get("secondary_education_pois") or []))
    evidence_parts.append(_format_report_pois("已排除的学校关键词误匹配", population.get("excluded_education_pois") or []))

    return "\n".join(part for part in evidence_parts if part)


def _build_messages(
    user_message: str,
    history: list[dict],
    memory_context: str,
    rag_docs: list[dict],
    address: Optional[str],
    evaluation_context: Optional[dict] = None,
) -> list[dict]:
    """构建发送给 LLM 的消息列表"""
    messages = []

    # 注入当前评估数据（最高优先级，让 AI 真正基于数据回答）
    if evaluation_context:
        ctx = evaluation_context
        dim_names = {
            "traffic": "交通与人流",
            "competition": "竞品分析",
            "population": "目标客群",
            "rent": "租金与成本",
            "facility": "配套设施",
            "policy": "政策环境",
        }
        dim_lines = []
        for dim, name in dim_names.items():
            dim_data = ctx.get("dimensions", {}).get(dim, {})
            if dim_data:
                score = dim_data.get("score", 0)
                weight = dim_data.get("weight", 0)
                detail = dim_data.get("detail", "")
                dim_lines.append(f"  - {name}：{score}分（权重{weight}%），{detail}")

        evidence_context = _build_evaluation_evidence_context(ctx)

        eval_summary = f"""【当前地址评估数据】
评估地址：{ctx.get('address', address or '未知')}
综合评分：{ctx.get('total_score', 0)}分，评级：{ctx.get('grade', '')}级（{ctx.get('grade_label', '')}）

各维度评分明细：
{chr(10).join(dim_lines)}

真实地图证据与 POI 清洗结果：
{evidence_context or '当前评估上下文未提供可展开的 POI 明细。'}

请基于以上真实评估数据回答用户的问题。引用具体分数、维度数据、POI 名称、距离和分类原因；不得补造上下文中没有的地图信息。"""
        messages.append({
            "role": "system",
            "content": eval_summary
        })

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
    if address and not evaluation_context:
        current_content = (
            f"用户关联地址（未完成正式评分，仅作通用问答上下文）：{address}\n\n"
            f"{user_message}\n\n"
            "注意：没有正式评估上下文时，不要输出确定性评分、评级或正式报告结论。"
        )

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
