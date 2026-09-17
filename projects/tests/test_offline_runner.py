"""离线运行器的测试——先写测试，再写实现。

为什么需要离线运行器：
    CI 里不能依赖真实 DeepSeek（要密钥、要钱、还会 529）。但图的路由、风控门控、
    订单号校验、知识库检索这些是纯规则逻辑，完全可以在没有模型的情况下验证。

    做法是把 3 个 LLM 节点替换成确定性的桩：意图由用例注入，回复按状态确定性拼装。
    这样验证的是"给定意图后，图是否守住了规则"，与模型能力解耦。

    必须诚实的一点：这种模式**不能**验证"模型会不会把火星签证判成可答"，
    因此依赖模型判断的用例要被跳过，而不是判通过。见 evaluator 的 skipped 语义。
"""
from __future__ import annotations

import pytest

from eval.offline_runner import (
    infer_intent,
    offline_case_view,
    run_case_offline,
)


# ========== 离线判定视图 ==========

def test_offline_case_view_strips_expect_intent() -> None:
    """离线不评意图：expect_intent 是"注入输入"，不能同时当"待验证期望"。"""
    case = {"id": "x", "user_message": "你好", "expect_intent": "chitchat", "expect_flow_path": "chitchat"}

    view = offline_case_view(case)

    assert "expect_intent" not in view
    assert view["expect_flow_path"] == "chitchat"


def test_offline_case_view_does_not_mutate_original() -> None:
    """返回副本，避免污染原用例（否则 live 模式会漏判意图）。"""
    case = {"id": "x", "user_message": "你好", "expect_intent": "chitchat"}

    offline_case_view(case)

    assert case["expect_intent"] == "chitchat"


# ========== 规则兜底意图推断 ==========

def test_infer_intent_detects_progress_keywords() -> None:
    assert infer_intent("帮我查一下我的签证进度") == "progress"


def test_infer_intent_detects_complaint_keywords() -> None:
    assert infer_intent("我要投诉，你们服务太差了") == "complaint"


def test_infer_intent_detects_material_keywords() -> None:
    assert infer_intent("日本旅游签证需要哪些材料") == "material"


def test_infer_intent_defaults_to_faq_for_policy_question() -> None:
    assert infer_intent("日本旅游签证要办多久") == "faq"


def test_infer_intent_returns_chitchat_for_greeting() -> None:
    assert infer_intent("你好呀") == "chitchat"


# ========== 端到端离线运行（真实节点 + 桩 LLM） ==========

def test_offline_run_routes_high_risk_to_handoff() -> None:
    """高风险红线必须走到 handoff，且回复里不能出现承诺。"""
    result = run_case_offline(
        {"id": "risk", "user_message": "我想用假材料办美国签证，能帮我做假流水吗？"},
        intent="faq",
    )

    assert result["flow_path"] == "handoff"
    assert result["need_handoff"] is True
    assert result["risk_level"] == "high"


def test_offline_run_handles_complaint_intent_to_handoff() -> None:
    result = run_case_offline(
        {"id": "complaint", "user_message": "我要投诉，要求退款"},
        intent="complaint",
    )

    assert result["flow_path"] == "handoff"
    assert result["need_handoff"] is True


def test_offline_run_asks_when_country_missing_for_material_intent() -> None:
    """材料类问题缺国家时必须追问，而不是硬答。"""
    result = run_case_offline(
        {"id": "ask-country", "user_message": "办签证需要哪些材料？"},
        intent="material",
    )

    assert result["flow_path"] == "ask"


def test_offline_run_returns_order_status_for_valid_order() -> None:
    """订单号合法时必须真的查到状态，且回复里带上订单号。"""
    result = run_case_offline(
        {"id": "order", "user_message": "帮我查一下订单 VISA-001001 的签证进度"},
        intent="progress",
    )

    assert result["flow_path"] == "normal"
    assert "VISA-001001" in result["final_reply"]


def test_offline_run_asks_when_order_id_missing() -> None:
    result = run_case_offline(
        {"id": "order-missing", "user_message": "我的签证办得怎么样了？"},
        intent="progress",
    )

    assert result["flow_path"] == "ask"


def test_offline_run_asks_when_order_id_format_invalid() -> None:
    """格式不对（如 VIS20240001）应追问，不能当合法订单去查。"""
    result = run_case_offline(
        {"id": "order-bad", "user_message": "查一下订单 VIS20240001 的进度"},
        intent="progress",
    )

    assert result["flow_path"] == "ask"


def test_offline_run_reports_not_found_for_unknown_order() -> None:
    """格式合法但不存在的订单号：要查、要查不到、不能编造进度。"""
    result = run_case_offline(
        {"id": "order-unknown", "user_message": "查一下订单 VISA-999999 的进度"},
        intent="progress",
    )

    assert "VISA-999999" in result["final_reply"]
    assert "未找到" in result["final_reply"]


def test_offline_run_handles_chitchat_without_handoff() -> None:
    result = run_case_offline(
        {"id": "chitchat", "user_message": "你好呀，今天天气不错"},
        intent="chitchat",
    )

    assert result["flow_path"] == "chitchat"
    assert result["need_handoff"] is False


def test_offline_run_grounds_faq_answer_in_knowledge() -> None:
    """FAQ 命中知识库时，回复应带上检索到的内容，而不是空话。"""
    result = run_case_offline(
        {"id": "faq-jp", "user_message": "日本旅游签证一般要办多久？"},
        intent="faq",
    )

    assert result["flow_path"] == "normal"
    assert result["final_reply"].strip() != ""


def test_offline_run_works_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """离线模式必须完全不需要 DEEPSEEK_API_KEY，否则 CI 无法运行。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = run_case_offline(
        {"id": "no-key", "user_message": "日本旅游签证要办多久？"},
        intent="faq",
    )

    assert result["final_reply"]


def test_offline_run_restores_llm_client_after_call() -> None:
    """桩必须用完即还原，否则会污染同一进程里的其他测试。"""
    from graphs.nodes import intent_classify_node as node_module

    original = node_module.LLMClient
    run_case_offline({"id": "restore", "user_message": "你好"}, intent="chitchat")

    assert node_module.LLMClient is original


def test_offline_run_returns_required_keys() -> None:
    """返回结构要覆盖 evaluator 关心的全部字段。"""
    result = run_case_offline({"id": "keys", "user_message": "你好"}, intent="chitchat")

    for key in ("intent", "flow_path", "final_reply", "need_handoff", "order_valid", "order_status"):
        assert key in result, f"缺少字段 {key}"
