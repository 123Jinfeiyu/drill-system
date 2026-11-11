"""客户回复生成通用流程（剧本演练 / Q&A 演练场共用）。

【P2-1 修复】customer_agent 与 practice_agent 原先各有一份约 60 行完全相同的
后处理逻辑（JSON 结束信号解析、空回复兜底、clean_customer_reply 清洗、
客服口吻 KS 错位 nudge 重试），统一收敛到这里，避免改一处漏一处。
调用方只保留各自差异部分：历史读取、prompt 构造、消息入库模型。
"""
import json

from app.services.llm_client import llm_client
from app.services.prompts import (
    CUSTOMER_EMPTY_REPLY,
    CUSTOMER_FALLBACK_REPLY,
    _looks_like_ks,
    clean_customer_reply,
)


async def generate_reply_text(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int = 600,
) -> tuple[str, bool]:
    """调用 LLM 生成客户回复并完成后处理，返回 (reply_text, is_finished)。

    LLM 异常原样向上抛出，由调用方的单事务回滚兜底（P1-2）。
    """
    content = await llm_client.chat(
        messages=messages,
        model=model,
        temperature=0.8,
        max_tokens=max_tokens,
    )
    # 推理模型偶发只输出推理、正文为空的异常，重试一次
    if not content.strip():
        content = await llm_client.chat(
            messages=messages,
            model=model,
            temperature=0.8,
            max_tokens=max_tokens,
        )

    # 尝试解析 JSON 结束信号，否则当纯文本
    is_finished = False
    reply_text = content
    try:
        if content.strip().startswith("{"):
            data = json.loads(content)
            if isinstance(data, dict):
                reply_text = str(data.get("content", content))
                is_finished = bool(data.get("is_finished", False))
    except json.JSONDecodeError:
        pass

    # 内容为空时视为生成异常：不结束会话，并给出兜底话术，避免空白气泡
    if not reply_text.strip():
        is_finished = False
        reply_text = CUSTOMER_EMPTY_REPLY

    # 清洗角色标签 + 校验是否出现客服口吻（角色错位则重试一次，仍错则兜底）
    reply_text = clean_customer_reply(reply_text)
    if _looks_like_ks(reply_text):
        nudge = messages + [
            {
                "role": "user",
                "content": (
                    "注意：你是客户本人，用第一人称'我'、抱怨口吻直接说出你的诉求。"
                    "绝不要用客服/官方话术，也不要输出'客服：'/'客户：'这类标签。"
                ),
            }
        ]
        content2 = await llm_client.chat(
            messages=nudge,
            model=model,
            temperature=0.6,
            max_tokens=max_tokens,
        )
        candidate = clean_customer_reply(content2)
        if not _looks_like_ks(candidate):
            reply_text = candidate
        else:
            reply_text = CUSTOMER_FALLBACK_REPLY
            is_finished = False

    return reply_text, is_finished
