"""Langfuse 追踪封装 - 按官方最佳实践集成 LangChain/LangGraph。

为什么单独封装：
- 与 main.py 解耦，追踪逻辑内聚在此模块
- 统一处理 Langfuse 未配置时的降级（不阻断业务）
- 集中管理 CallbackHandler 创建与 trace 属性传播

用法：
    from utils.langfuse_trace import langfuse_available, get_langfuse_callback, LangfuseTraceContext

    if langfuse_available():
        with LangfuseTraceContext(trace_name="visa-customer-/run", session_id=..., tags=[...]):
            handler = get_langfuse_callback()
            await graph.ainvoke(payload, config={"callbacks": [handler], ...})
            langfuse_flush()

环境变量（见 .env.example）：
- LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

logger = logging.getLogger(__name__)

try:
    from langfuse import get_client, observe, propagate_attributes
    from langfuse.langchain import CallbackHandler
    _LANGFUSE_IMPORTED = True
except ImportError:  # langfuse 未安装时全部降级为空操作
    _LANGFUSE_IMPORTED = False

    def observe(**_: Any):
        return lambda f: f

    def get_client() -> Any:  # pragma: no cover - 仅降级路径
        return None

    def propagate_attributes(**_: Any):
        return _null_context()

    class CallbackHandler:  # type: ignore[no-redef]
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

    class _null_context:
        def __enter__(self):
            return self

        def __exit__(self, *_: Any) -> None:
            pass


def langfuse_available() -> bool:
    """Langfuse 是否可用（已安装且已配置密钥）。"""
    if not _LANGFUSE_IMPORTED:
        return False
    try:
        import os
        return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))
    except Exception:
        return False


def get_langfuse_callback() -> Optional[CallbackHandler]:
    """创建 Langfuse CallbackHandler（LangChain/LangGraph 集成）。

    传入 config={"callbacks": [handler]} 后，LangGraph 的 LLM 调用、
    工具、检索会自动生成嵌套 span，并捕获模型名与 token 用量。
    """
    if not langfuse_available():
        return None
    return CallbackHandler()


@contextmanager
def LangfuseTraceContext(
    trace_name: str,
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Iterator[None]:
    """在 trace 根上传播属性（session_id/user_id/tags），供子观察继承。

    必须在 @observe 装饰的函数内部使用；配合 CallbackHandler 实现
    一层 trace 根 + 嵌套 generation span 的完整层级。
    """
    if not langfuse_available():
        yield
        return
    attrs: dict = {"trace_name": trace_name}
    if session_id:
        attrs["session_id"] = session_id
    if user_id:
        attrs["user_id"] = user_id
    if tags:
        attrs["tags"] = tags
    with propagate_attributes(**attrs):
        yield


def langfuse_flush() -> None:
    """主动 flush，避免进程退出前丢 span（短请求路径必须调用）。"""
    if not langfuse_available():
        return
    try:
        get_client().flush()
    except Exception:
        logger.debug("langfuse flush skipped", exc_info=True)
