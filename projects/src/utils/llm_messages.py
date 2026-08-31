"""LLM 消息构造：返回 LangChain BaseMessage 实例（SystemMessage/HumanMessage）。

为什么：LLMClient 底层是 langchain-openai ChatOpenAI，stream() 要求 messages 中
至少有一个 HumanMessage 实例（纯 dict 会触发 ValueError）。序列化时未设置 name
字段，Coze 网关路径同样兼容（不会出现 GatewayErr: dict has no attribute 'name'）。
"""
from __future__ import annotations

import json
from typing import Any, List

from langchain_core.messages import HumanMessage, SystemMessage


def ensure_text(value: Any) -> str:
    """把任意上游值收成可进 messages.content 的纯字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def get_text_content(content: Any) -> str:
    """安全提取 LLM 返回的文本内容。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if content and isinstance(content[0], str):
            return " ".join(content)
        text_parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return " ".join(text_parts)
    return str(content)


def build_chat_messages(system_prompt: Any, user_prompt: Any) -> List[Any]:
    """
    构造 LLMClient 可用的 messages。

    返回 SystemMessage/HumanMessage 实例（不带 name），本地 ChatOpenAI
    直连与 Coze 网关两条路径均可用。
    """
    return [
        SystemMessage(content=ensure_text(system_prompt)),
        HumanMessage(content=ensure_text(user_prompt)),
    ]
