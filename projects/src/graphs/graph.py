"""签证客服助手-Demo - 主图编排（v2：风控全链路覆盖 + 5类意图）"""
from langgraph.graph import StateGraph, END
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from utils.context import Context

from graphs.state import (
    GlobalState,
    GraphInput,
    GraphOutput,
)
from graphs.nodes.intent_classify_node import intent_classify_node
from graphs.nodes.complaint_handoff_node import complaint_handoff_node
from graphs.nodes.order_validate_node import order_validate_node
from graphs.nodes.knowledge_retrieval_node import knowledge_retrieval_node
from graphs.nodes.slot_filling_node import slot_filling_node
from graphs.nodes.risk_assessment_node import risk_assessment_node
from graphs.nodes.order_progress_query_node import order_progress_query_node
from graphs.nodes.response_generate_node import response_generate_node


def route_by_intent(state: GlobalState) -> str:
    """
    title: 意图路由
    desc: 根据5类意图分流：complaint直达转人工，chitchat直达回复，progress走订单验证，faq/material走槽位填充
    """
    intent = state.intent

    if intent == "complaint":
        return "投诉转人工"
    elif intent == "chitchat":
        return "闲聊回复"
    elif intent == "progress":
        return "验证订单号"
    else:
        return "填充槽位"


def route_after_slot_filling(state: GlobalState) -> str:
    """
    title: 槽位填充后路由
    desc: 检查必填信息是否齐全。有缺失→追问（仍进风控）；齐全→知识库检索
    """
    if state.missing_slots:
        return "追问缺失信息"
    else:
        return "检索知识库"


def route_after_order_validate(state: GlobalState) -> str:
    """
    title: 订单验证后路由
    desc: 订单号有效→查进度；无效→追问（仍进风控）
    """
    if state.order_valid:
        return "查询进度"
    else:
        return "追问订单号"


# 创建状态图，指定入参和出参
builder = StateGraph(GlobalState, input_schema=GraphInput, output_schema=GraphOutput)

# 添加节点
builder.add_node(
    "intent_classify",
    intent_classify_node,
    metadata={"type": "agent", "llm_cfg": "config/intent_classify_llm_cfg.json"}
)
builder.add_node("complaint_handoff", complaint_handoff_node)
builder.add_node("order_validate", order_validate_node)
builder.add_node("knowledge_retrieval", knowledge_retrieval_node)
builder.add_node(
    "slot_filling",
    slot_filling_node,
    metadata={"type": "agent", "llm_cfg": "config/slot_filling_llm_cfg.json"}
)
builder.add_node("risk_assessment", risk_assessment_node)
builder.add_node("order_progress_query", order_progress_query_node)
builder.add_node(
    "response_generate",
    response_generate_node,
    metadata={"type": "agent", "llm_cfg": "config/response_generate_llm_cfg.json"}
)

# 设置入口点
builder.set_entry_point("intent_classify")

# ========== 意图路由（第一层分支）==========
builder.add_conditional_edges(
    source="intent_classify",
    path=route_by_intent,
    path_map={
        "投诉转人工": "complaint_handoff",
        "闲聊回复": "response_generate",
        "验证订单号": "order_validate",
        "填充槽位": "slot_filling"
    }
)

# ========== 投诉 → 风控 → 回复（全链路覆盖）==========
builder.add_edge("complaint_handoff", "risk_assessment")

# ========== 槽位填充后路由（第二层分支）==========
builder.add_conditional_edges(
    source="slot_filling",
    path=route_after_slot_filling,
    path_map={
        "追问缺失信息": "risk_assessment",
        "检索知识库": "knowledge_retrieval"
    }
)

# ========== 知识库检索 → 风控 ==========
builder.add_edge("knowledge_retrieval", "risk_assessment")

# ========== 订单验证后路由（第三层分支）==========
builder.add_conditional_edges(
    source="order_validate",
    path=route_after_order_validate,
    path_map={
        "查询进度": "order_progress_query",
        "追问订单号": "risk_assessment"
    }
)

# ========== 订单查询 → 风控 ==========
builder.add_edge("order_progress_query", "risk_assessment")

# ========== 风控 → 回复生成 → 结束 ==========
builder.add_edge("risk_assessment", "response_generate")
builder.add_edge("response_generate", END)

# 编译图
main_graph = builder.compile()
