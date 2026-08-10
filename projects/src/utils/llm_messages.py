"""Coze LLMClient 消息构造：网关要求 role/content 纯文本，勿传带 name 的 Message 对象。"""
from __future__ import annotations

import json
from typing import Any, List, Mapping


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


def build_chat_messages(system_prompt: Any, user_prompt: Any) -> List[Mapping[str, str]]:
    """
    构造 Coze LLMClient 可用的 messages。

    使用 OpenAI 风格 dict，避免 LangChain SystemMessage/HumanMessage 带 name
    被序列化后触发 GatewayErr: dict has no attribute 'name'。
    """
    return [
        {"role": "system", "content": ensure_text(system_prompt)},
        {"role": "user", "content": ensure_text(user_prompt)},
    ]
