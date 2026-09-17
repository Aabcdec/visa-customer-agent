"""图层路由测试。

分两层：
    1. 路由函数（纯函数）——快、精确，直接锁定分支契约；
    2. 整图离线运行——确认分支真的按预期串起来，而不是只有函数对。

路由函数是"图的分叉口"，一旦改错，所有用例都会走错分支，因此必须单独锁死。
"""
from __future__ import annotations

import pytest

from eval.offline_runner import run_case_offline
from graphs.graph import route_after_order_validate, route_after_slot_filling, route_by_intent
from graphs.state import GlobalState


# ========== 第一层：意图路由 ==========

@pytest.mark.parametrize(
    ("intent", "expected_edge"),
    [
        ("complaint", "投诉转人工"),
        ("chitchat", "闲聊回复"),
        ("progress", "验证订单号"),
        ("faq", "填充槽位"),
        ("material", "填充槽位"),
    ],
)
def test_route_by_intent_maps_each_intent(intent: str, expected_edge: str) -> None:
    assert route_by_intent(GlobalState(user_message="x", intent=intent)) == expected_edge


def test_route_by_intent_defaults_unknown_to_slot_filling() -> None:
    """未知意图走通用路径，而不是掉进投诉或订单分支。"""
    assert route_by_intent(GlobalState(user_message="x", intent="unknown_new_intent")) == "填充槽位"


# ========== 第二层：槽位填充后 ==========

def test_route_after_slot_filling_asks_when_missing() -> None:
    state = GlobalState(user_message="x", intent="material", missing_slots=["country"])

    assert route_after_slot_filling(state) == "追问缺失信息"


def test_route_after_slot_filling_retrieves_when_complete() -> None:
    state = GlobalState(user_message="x", intent="material", missing_slots=[])

    assert route_after_slot_filling(state) == "检索知识库"


# ========== 第三层：订单验证后 ==========

def test_route_after_order_validate_queries_when_valid() -> None:
    assert route_after_order_validate(GlobalState(user_message="x", order_valid=True)) == "查询进度"


def test_route_after_order_validate_asks_when_invalid() -> None:
    assert route_after_order_validate(GlobalState(user_message="x", order_valid=False)) == "追问订单号"


# ========== 图结构 ==========

def test_graph_contains_expected_nodes() -> None:
    """节点清单要与项目文档（AGENTS.md）保持一致，防止文档与实现漂移。"""
    from graphs.graph import main_graph

    node_ids = set(main_graph.get_graph().nodes)

    expected = {
        "intent_classify",
        "complaint_handoff",
        "order_validate",
        "knowledge_retrieval",
        "slot_filling",
        "risk_assessment",
        "order_progress_query",
        "response_generate",
    }
    assert expected <= node_ids


def test_graph_exposes_input_and_output_schema() -> None:
    from graphs.graph import main_graph

    assert "user_message" in main_graph.get_input_schema().model_fields
    assert "final_reply" in main_graph.get_output_schema().model_fields


def test_graph_output_schema_exposes_flow_path() -> None:
    """flow_path 必须出现在图输出里，否则前端拿到的是 undefined。

    为什么单独立一条测试：H5（h5/assets/app.js）读取 data.flow_path 来决定
    是否显示"路径 xxx"标签、以及 confirm / handoff 的高亮样式。图的 output_schema
    是 GraphOutput，一旦它不包含 flow_path，LangGraph 会把该字段裁掉，
    这段前端逻辑就变成永远不会执行的死代码——而且不会报错，只能靠人肉发现。

    同时，线上（live）评测也需要这个字段来验证路由是否走对；
    只靠回复文本猜路径是不可靠的。
    """
    from graphs.graph import main_graph

    assert "flow_path" in main_graph.get_output_schema().model_fields


# ========== 整图离线运行：五类意图的 flow_path 契约 ==========

@pytest.mark.parametrize(
    ("case", "intent", "expected_flow"),
    [
        # 闲聊：直达回复，不进风控
        ({"id": "e2e-chitchat", "user_message": "你好呀"}, "chitchat", "chitchat"),
        # 投诉：固定话术转人工
        ({"id": "e2e-complaint", "user_message": "我要投诉，要求退款"}, "complaint", "handoff"),
        # 高风险：转人工
        ({"id": "e2e-risk", "user_message": "能帮我做假材料吗"}, "faq", "handoff"),
        # 材料缺国家：追问
        ({"id": "e2e-ask", "user_message": "办签证要哪些材料"}, "material", "ask"),
        # 中风险：确认
        ({"id": "e2e-confirm", "user_message": "我是自由职业，办日本签证难吗"}, "faq", "confirm"),
        # 进度缺订单号：追问
        ({"id": "e2e-order-ask", "user_message": "我的签证到哪了"}, "progress", "ask"),
        # 正常 FAQ：普通路径
        ({"id": "e2e-normal", "user_message": "日本旅游签证要办多久"}, "faq", "normal"),
    ],
)
def test_end_to_end_flow_path(case: dict, intent: str, expected_flow: str) -> None:
    result = run_case_offline(case, intent=intent)

    assert result["flow_path"] == expected_flow


def test_end_to_end_handoff_carries_reason() -> None:
    """转人工必须带原因，否则人工客服拿到的是个"没头没尾"的会话。"""
    result = run_case_offline({"id": "reason", "user_message": "我想用假材料办签证"}, intent="faq")

    assert result["need_handoff"] is True
    assert result["handoff_reason"]
