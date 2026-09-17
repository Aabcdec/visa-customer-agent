"""Langfuse 可观测性封装测试。

目标不是测试 Langfuse 官方 SDK，而是保护本项目的降级契约：
    - 没配密钥时，业务必须照常运行，且不创建 CallbackHandler；
    - 配好密钥时，才创建回调并传播 session/tags；
    - flush 或 SDK 异常绝不能击穿主链路。

这些测试全部离线，不向 Langfuse Cloud 发请求。
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

import utils.langfuse_trace as trace


def test_available_false_when_keys_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(trace, "_LANGFUSE_IMPORTED", True)

    assert trace.langfuse_available() is False


def test_available_requires_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(trace, "_LANGFUSE_IMPORTED", True)

    assert trace.langfuse_available() is False


def test_available_true_when_imported_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(trace, "_LANGFUSE_IMPORTED", True)

    assert trace.langfuse_available() is True


def test_callback_is_none_when_langfuse_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace, "langfuse_available", lambda: False)

    assert trace.get_langfuse_callback() is None


def test_callback_is_created_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    created = object()
    monkeypatch.setattr(trace, "langfuse_available", lambda: True)
    monkeypatch.setattr(trace, "CallbackHandler", lambda: created)

    assert trace.get_langfuse_callback() is created


def test_trace_context_is_noop_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace, "langfuse_available", lambda: False)

    with trace.LangfuseTraceContext("test", session_id="session-1"):
        observed = "business-still-runs"

    assert observed == "business-still-runs"


def test_trace_context_propagates_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    @contextmanager
    def fake_propagate(**kwargs):
        captured.update(kwargs)
        yield

    monkeypatch.setattr(trace, "langfuse_available", lambda: True)
    monkeypatch.setattr(trace, "propagate_attributes", fake_propagate)

    with trace.LangfuseTraceContext(
        "visa-customer-/run",
        session_id="run-123",
        user_id="user-1",
        tags=["visa-customer", "run"],
    ):
        pass

    assert captured == {
        "trace_name": "visa-customer-/run",
        "session_id": "run-123",
        "user_id": "user-1",
        "tags": ["visa-customer", "run"],
    }


def test_flush_is_noop_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace, "langfuse_available", lambda: False)
    monkeypatch.setattr(trace, "get_client", lambda: (_ for _ in ()).throw(AssertionError("must not call")))

    trace.langfuse_flush()


def test_flush_failure_does_not_break_business(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenClient:
        def flush(self) -> None:
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(trace, "langfuse_available", lambda: True)
    monkeypatch.setattr(trace, "get_client", lambda: BrokenClient())

    # 可观测性是旁路能力，供应商不可用时必须降级而不是击穿业务。
    trace.langfuse_flush()
