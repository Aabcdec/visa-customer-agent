"""轻量运行上下文 - 替代 coze_coding_utils.runtime_ctx.context。

为什么自建：去掉 Coze 依赖后，节点签名中的 Runtime[Context] 需要一个
Context 类型。langgraph 的 Runtime 泛型只要求一个可用的 context 对象，
这里提供最简实现：run_id 贯穿请求，附带 method/headers 供日志使用。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


class Context:
    """请求级运行上下文。

    - run_id: 一次请求/一次图运行的唯一标识（由 HTTP 层生成后注入）
    - method: 入口方式（run/stream_run/node_run/...），仅用于日志
    - headers: 原始请求头快照，供需要上游信息的节点使用
    """

    def __init__(
        self,
        run_id: Optional[str] = None,
        method: str = "",
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.run_id: str = run_id or uuid.uuid4().hex
        self.method: str = method
        self.headers: Dict[str, str] = dict(headers or {})
        # 兼容 coze 的 default_headers / 附加字段：统一放 extras
        self.extras: Dict[str, Any] = {}

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"Context(run_id={self.run_id!r}, method={self.method!r})"


def new_context(
    method: str = "",
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Context:
    """创建新上下文；兼容旧调用签名 new_context(method=..., headers=...)。"""
    run_id = kwargs.get("run_id") or kwargs.get("run_id")
    return Context(run_id=run_id, method=method, headers=headers)
