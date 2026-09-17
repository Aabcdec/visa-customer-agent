"""订单进度查询节点与 Mock 工具测试。

最关键的红线：**查不到就说查不到，绝不能编造进度**。
用户拿这个结果去判断自己的签证状态，编造会直接导致投诉甚至法律问题。
"""
from __future__ import annotations

import pytest

from graphs.nodes.order_progress_query_node import order_progress_query_node
from graphs.state import OrderProgressInput
from tools.order_progress_tool import MOCK_ORDER_DATABASE, query_order_progress


def _run_node(fake_runtime, order_id: str):
    return order_progress_query_node(OrderProgressInput(order_id=order_id), {}, fake_runtime)


# ========== Mock 工具 ==========

def test_tool_finds_known_order() -> None:
    result = query_order_progress("VISA-001001")

    assert result["found"] is True
    assert result["country"] == "日本"
    assert result["status"]


def test_tool_is_case_insensitive() -> None:
    assert query_order_progress("visa-001001")["found"] is True


def test_tool_rejects_empty_order_id() -> None:
    result = query_order_progress("")

    assert result["found"] is False
    assert result["message"]


@pytest.mark.parametrize("bad", [None, 123, {}])
def test_tool_rejects_non_string_order_id(bad) -> None:
    """入参类型不对时要返回结构化失败，而不是抛异常。"""
    result = query_order_progress(bad)

    assert result["found"] is False


def test_tool_reports_not_found_for_unknown_order() -> None:
    result = query_order_progress("VISA-999999")

    assert result["found"] is False
    assert "VISA-999999" in result["message"]


def test_tool_message_lists_available_ids_for_debugging() -> None:
    """"未找到"的提示里带上可用测试订单号，本地联调时不用去翻代码。"""
    result = query_order_progress("VISA-999999")

    assert "VISA-001001" in result["message"]


def test_all_mock_orders_have_required_fields() -> None:
    """Mock 数据结构统一，避免某个订单缺字段导致节点拼出 None。"""
    required = {"order_id", "country", "visa_type", "status", "submit_date", "estimated_days", "current_step", "steps"}
    for order_id, order in MOCK_ORDER_DATABASE.items():
        assert required <= set(order), f"{order_id} 缺字段: {required - set(order)}"


# ========== 节点行为 ==========

def test_node_returns_status_for_valid_order(fake_runtime) -> None:
    result = _run_node(fake_runtime, "VISA-001001")

    assert "VISA-001001" in result.order_status
    assert "日本" in result.order_status


def test_node_includes_progress_steps(fake_runtime) -> None:
    """进度不能只给一个状态词，要给出环节列表，用户才知道走到哪一步了。"""
    result = _run_node(fake_runtime, "VISA-001001")

    assert "材料提交" in result.order_status
    assert "护照返回" in result.order_status


def test_node_does_not_fabricate_for_unknown_order(fake_runtime) -> None:
    """核心红线：查不到时不能出现任何进展性描述。"""
    result = _run_node(fake_runtime, "VISA-999999")

    assert "未找到" in result.order_status
    assert "审理中" not in result.order_status
    assert "已出签" not in result.order_status


def test_node_handles_empty_order_id(fake_runtime) -> None:
    result = _run_node(fake_runtime, "")

    assert "订单号" in result.order_status


def test_node_falls_back_when_tool_raises(fake_runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    """插件异常时给兜底话术，不能让整条图崩掉。"""
    import graphs.nodes.order_progress_query_node as module

    def _boom(_order_id):
        raise RuntimeError("mock plugin down")

    monkeypatch.setattr(module, "query_order_progress", _boom)

    result = _run_node(fake_runtime, "VISA-001001")

    assert "异常" in result.order_status
    assert "VISA-001001" in result.order_status


def test_node_falls_back_when_tool_returns_non_dict(fake_runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    """插件返回类型不对时也要兜底，避免 AttributeError 冒到用户面前。"""
    import graphs.nodes.order_progress_query_node as module

    monkeypatch.setattr(module, "query_order_progress", lambda _order_id: "not a dict")

    result = _run_node(fake_runtime, "VISA-001001")

    assert "异常" in result.order_status or "稍后重试" in result.order_status
