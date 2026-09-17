"""订单号验证节点测试。

这个节点的职责边界很关键：它只负责"能不能去查进度"，不负责编造进度。
因此要覆盖：
    - 从整句里提取订单号（用户往往把订单号嵌在一句话里）；
    - 没有订单号时追问而不是查空；
    - 格式不对时给出格式提示而不是当成合法订单；
    - 大小写归一化。
"""
from __future__ import annotations

import pytest

from graphs.nodes.order_validate_node import order_validate_node
from graphs.state import OrderValidateInput


def _run(fake_runtime, **overrides):
    return order_validate_node(OrderValidateInput(**overrides), {}, fake_runtime)


def test_extracts_order_id_from_full_sentence(fake_runtime) -> None:
    result = _run(fake_runtime, user_message="帮我查一下订单 VISA-001001 的签证进度")

    assert result.order_id == "VISA-001001"
    assert result.order_valid is True


def test_normalizes_lowercase_order_id(fake_runtime) -> None:
    """用户可能小写输入，归一化后才能命中 Mock 数据。"""
    result = _run(fake_runtime, user_message="查一下 visa-001002 的进度")

    assert result.order_id == "VISA-001002"
    assert result.order_valid is True


def test_prefers_explicit_order_id_field(fake_runtime) -> None:
    """上游已提取到订单号时，优先使用它而不是重新从整句里猜。"""
    result = _run(fake_runtime, order_id="VISA-001003", user_message="查进度")

    assert result.order_id == "VISA-001003"
    assert result.order_valid is True


def test_asks_when_order_id_absent(fake_runtime) -> None:
    result = _run(fake_runtime, user_message="我的签证办得怎么样了？")

    assert result.order_valid is False
    assert result.order_id == ""
    assert "订单号" in result.order_follow_up


def test_follow_up_explains_required_format(fake_runtime) -> None:
    """追问要带上格式示例，否则用户不知道去哪找、长什么样。"""
    result = _run(fake_runtime, user_message="帮我查进度")

    assert "VISA-" in result.order_follow_up


@pytest.mark.parametrize("bad", ["VIS20240001", "VISA-", "订单号12345", "VISA-ABC"])
def test_rejects_malformed_order_id(fake_runtime, bad: str) -> None:
    """格式不合法时必须追问，绝不能拿去查询（否则会查出一堆"未找到"）。"""
    result = _run(fake_runtime, user_message=f"查一下订单 {bad} 的进度")

    assert result.order_valid is False
    assert result.order_follow_up


def test_malformed_order_id_follow_up_echoes_user_input(fake_runtime) -> None:
    """提示要回显用户输入，用户才知道系统识别到了什么。"""
    result = _run(fake_runtime, order_id="VIS20240001", user_message="查进度")

    assert "VIS20240001" in result.order_follow_up


def test_empty_message_is_treated_as_missing(fake_runtime) -> None:
    result = _run(fake_runtime, user_message="")

    assert result.order_valid is False
    assert result.order_follow_up
