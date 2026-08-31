"""DeepSeek LLM 直连客户端 - 替代 coze_coding_dev_sdk.LLMClient。

为什么自建：去掉 Coze 依赖后，3 个 LLM 节点（intent_classify / slot_filling /
response_generate）需要一个统一的 LLM 调用入口。底层直接使用
langchain-openai 的 ChatOpenAI 指向 DeepSeek 的 OpenAI 兼容端点。

环境变量：
- DEEPSEEK_API_KEY: 必填，DeepSeek 平台密钥
- DEEPSEEK_BASE_URL: 可选，默认 https://api.deepseek.com
"""
from __future__ import annotations

import os
import logging
from typing import Any, List, Optional

from langchain_core.messages import BaseMessage, AIMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class LLMClient:
    """DeepSeek OpenAI 兼容客户端，接口对齐原 coze LLMClient.invoke/stream。"""

    def __init__(self, ctx: Any = None) -> None:
        self.ctx = ctx
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        if not self.api_key:
            logger.error("DEEPSEEK_API_KEY 未设置，LLM 调用将失败")
        # 复用项目内模型名映射：config/*.json 里统一写 deepseek-chat

    def _create_llm(
        self,
        model: str,
        temperature: float,
        top_p: float,
        max_completion_tokens: int,
        streaming: bool,
    ) -> ChatOpenAI:
        return ChatOpenAI(
            model=model or DEFAULT_MODEL,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=temperature,
            top_p=top_p,
            max_completion_tokens=max_completion_tokens,
            streaming=streaming,
            timeout=300,
            max_retries=2,
        )

    def invoke(
        self,
        messages: List[BaseMessage],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        top_p: float = 0.7,
        max_completion_tokens: int = 1000,
        **_: Any,
    ) -> AIMessage:
        """非流式调用，返回 AIMessage（与原 LLMClient.invoke 行为一致）。"""
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未设置，无法调用 LLM")
        llm = self._create_llm(
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_completion_tokens=max_completion_tokens,
            streaming=False,
        )
        try:
            return llm.invoke(messages)
        except Exception as e:
            logger.error(f"DeepSeek invoke failed: {e}")
            raise

    def stream(
        self,
        messages: List[BaseMessage],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        top_p: float = 0.7,
        max_completion_tokens: int = 1000,
        **_: Any,
    ):
        """流式调用，逐块产出 BaseMessageChunk。"""
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未设置，无法调用 LLM")
        llm = self._create_llm(
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_completion_tokens=max_completion_tokens,
            streaming=True,
        )
        for chunk in llm.stream(messages):
            yield chunk
