"""投诉转人工节点测试。

设计要点：这个节点**不调用模型**，用固定话术 + 结构化摘要。
为什么要专门测：一旦这里被改成"让模型自由发挥"，退款/造假这类场景就存在
模型顺口答应的风险。测试要锁住"固定话术 + 必转人工 + 摘要含关键要素"。
"""
from __future__ import annotations

import pytest

from graphs.nodes.complaint_handoff_node import complaint_handoff_node
from graphs.state import ComplaintHandoffInput


def _run(fake_runtime, **overrides):
    return complaint_handoff_node(ComplaintHandoffInput(**overrides), {}, fake_runtime)


def test_complaint_always_hands_off(fake_runtime) -> None:
    result = _run(fake_runtime, user_message="我要投诉你们的服务", intent="complaint")

    assert result.need_handoff is True
    assert result.flow_path == "handoff"
    assert result.handoff_reason


@pytest.mark.parametrize(
    ("message", "expected_reason"),
    [
        ("我要退款", "用户要求退款"),
        ("你们能保证出签吗", "用户要求保证出签结果"),
        ("我想用假材料办签证", "用户涉及材料造假请求"),
        ("我要投诉", "用户提出投诉"),
    ],
)
def test_reason_is_classified_by_keyword(fake_runtime, message: str, expected_reason: str) -> None:
    """摘要要把诉求归类，人工客服才能一眼看出该转给谁。"""
    result = _run(fake_runtime, user_message=message, intent="complaint")

    assert expected_reason in result.complaint_summary


def test_summary_contains_intent_country_and_original_words(fake_runtime) -> None:
    """摘要必须包含意图、国家、原话——这是人工介入所需的最小上下文。"""
    result = _run(
        fake_runtime,
        user_message="我要退款，日本签证不办了",
        intent="complaint",
        country="日本",
    )

    assert "complaint" in result.complaint_summary
    assert "日本" in result.complaint_summary
    assert "退款" in result.complaint_summary


def test_summary_marks_missing_country_explicitly(fake_runtime) -> None:
    """国家缺失时写"未提供"，而不是留空让客服以为没有这一项。"""
    result = _run(fake_runtime, user_message="我要投诉", intent="complaint", country="")

    assert "未提供" in result.complaint_summary


def test_unknown_reason_falls_back_to_generic_label(fake_runtime) -> None:
    """没匹配到关键词也不能出现空原因。"""
    result = _run(fake_runtime, user_message="你们这个流程有点奇怪", intent="complaint")

    assert result.complaint_summary
    assert result.handoff_reason


def test_summary_truncates_overlong_message(fake_runtime) -> None:
    """超长原话要截断，避免摘要被判成垃圾信息或撑爆下游。"""
    long_message = "我要投诉" + "很长的描述" * 100

    result = _run(fake_runtime, user_message=long_message, intent="complaint")

    assert len(result.complaint_summary) < len(long_message)
