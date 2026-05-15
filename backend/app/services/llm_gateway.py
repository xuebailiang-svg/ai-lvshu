"""
大模型网关服务 (LLM Gateway)
支持多种推理模型，通过配置动态切换：
- 本地 Ollama (Qwen/Llama/ChatGLM 等)
- OpenAI API (gpt-4o / gpt-4o-mini)
- 阿里云百炼 (qwen-plus / qwen-turbo)
- 自定义 OpenAI 兼容接口

所有模型统一通过 OpenAI SDK 调用（兼容接口）
"""
import logging
import asyncio
from typing import Optional, AsyncGenerator, Any
from sqlalchemy.orm import Session
from app.core.crypto import decrypt_config_value
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)


def get_llm_config(db: Session) -> dict:
    """从数据库读取 LLM 配置（key 格式：llm.xxx，与前端 SettingsView 保存格式一致）"""
    keys = [
        "llm.type",        # local | api
        "llm.api_key",     # API Key（local/Ollama 时值为 'ollama' 或空）
        "llm.local_url",   # Ollama base_url: http://localhost:11434/v1
        "llm.api_base",    # 云端 API base_url
        "llm.model_name",  # 主模型名称
        "llm.fast_model",  # 快速模型（可选）
        "llm.temperature", # 温度参数
        "llm.max_tokens",  # 最大 token 数
    ]
    configs = db.query(SystemConfig).filter(
        SystemConfig.config_key.in_(keys),
        SystemConfig.is_active == True
    ).all()
    cfg = {c.config_key: decrypt_config_value(c.config_value) for c in configs}

    llm_type = cfg.get("llm.type", "local")  # local | api

    if llm_type == "local":
        # 本地 Ollama 模式
        provider = "ollama"
        base_url = cfg.get("llm.local_url") or "http://localhost:11434/v1"
        api_key = cfg.get("llm.api_key") or "ollama"
    else:
        # 云端 API 模式（OpenAI / 阿里云 / 自定义）
        provider = "custom"
        base_url = cfg.get("llm.api_base") or ""
        api_key = cfg.get("llm.api_key") or ""

    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": cfg.get("llm.model_name") or "qwen2.5:32b",
        "temperature": float(cfg.get("llm.temperature") or "0.7"),
        "max_tokens": int(cfg.get("llm.max_tokens") or "4096"),
        "llm_type": llm_type,
    }


def _is_configured(cfg: dict) -> bool:
    """判断 LLM 是否已配置（避免误判为未配置而走 mock 分支）"""
    if cfg["llm_type"] == "local":
        # 本地 Ollama：只要有 base_url 和 model 就算已配置
        return bool(cfg.get("base_url") and cfg.get("model"))
    else:
        # 云端 API：需要 api_key
        return bool(cfg.get("api_key"))


def _build_client(cfg: dict):
    """根据配置构建 OpenAI 客户端"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("请安装 openai 包: pip install openai")

    provider = cfg["provider"]

    if provider == "ollama":
        base_url = cfg.get("base_url") or "http://localhost:11434/v1"
        return AsyncOpenAI(api_key="ollama", base_url=base_url, timeout=45.0)

    elif provider == "aliyun":
        base_url = cfg.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return AsyncOpenAI(api_key=cfg["api_key"], base_url=base_url, timeout=45.0)

    elif provider == "custom":
        kwargs: dict[str, Any] = {"api_key": cfg["api_key"] or "none", "timeout": 45.0}
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return AsyncOpenAI(**kwargs)

    else:  # openai (默认)
        kwargs = {"api_key": cfg["api_key"], "timeout": 45.0}
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return AsyncOpenAI(**kwargs)


async def chat_completion(
    messages: list[dict],
    db: Session,
    stream: bool = False,
    system_prompt: Optional[str] = None,
) -> str:
    """
    非流式对话完成
    返回完整的回复文本
    """
    cfg = get_llm_config(db)
    if not _is_configured(cfg):
        logger.warning(f"LLM 未配置（type={cfg['llm_type']}），返回占位文本")
        return _mock_response(messages)

    if system_prompt:
        messages = [{"role": "system", "content": system_prompt}] + messages

    try:
        client = _build_client(cfg)
        response = await client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"LLM 调用失败 ({cfg['provider']}): {e}")
        return f"[LLM 调用失败: {str(e)[:100]}]"


async def chat_completion_stream(
    messages: list[dict],
    db: Session,
    system_prompt: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    流式对话完成
    逐 token 生成，用于前端实时展示
    """
    cfg = get_llm_config(db)
    if not _is_configured(cfg):
        # 无配置时模拟流式输出
        logger.warning(f"LLM 未配置（type={cfg['llm_type']}），返回模拟流式输出")
        mock = _mock_response(messages)
        for char in mock:
            yield char
            await asyncio.sleep(0.02)
        return

    if system_prompt:
        messages = [{"role": "system", "content": system_prompt}] + messages

    logger.info(f"LLM 流式调用：provider={cfg['provider']}, model={cfg['model']}, base_url={cfg['base_url']}")

    try:
        client = _build_client(cfg)
        stream_resp = await client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
            stream=True,
        )
        async for chunk in stream_resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as e:
        logger.error(f"LLM 流式调用失败 ({cfg['provider']}): {e}")
        yield f"\n[LLM 调用失败: {str(e)[:200]}]"


def _mock_response(messages: list[dict]) -> str:
    """未配置 LLM 时的占位回复"""
    return (
        "【提示：当前未配置大模型，以下为模拟回复】\n\n"
        "根据系统评分结果，该地址综合条件良好，建议重点关注周边竞品密度和目标客群分布。"
        "请在系统配置中填写大模型 API Key 以获取真实的 AI 分析报告。"
    )


async def test_llm_connection(db: Session) -> dict:
    """测试 LLM 连通性"""
    cfg = get_llm_config(db)
    try:
        result = await chat_completion(
            messages=[{"role": "user", "content": "请回复'连接成功'"}],
            db=db
        )
        return {"success": True, "provider": cfg["provider"], "model": cfg["model"], "response": result[:50]}
    except Exception as e:
        return {"success": False, "provider": cfg["provider"], "error": str(e)}
