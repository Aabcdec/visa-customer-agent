"""离线运行器：不调用任何真实模型，在进程内跑完整张图。

为什么需要它：
    CI 里不能依赖真实 DeepSeek——要密钥、要花钱、还会偶发 529 过载。但图里的
    路由、风控门控、订单号校验、知识库检索都是纯规则逻辑，完全可以在没有模型的
    情况下验证。把它做成确定性 harness，才能让"评测"成为可持续的门禁。

做法：
    把 3 个 LLM 节点（intent_classify / slot_filling / response_generate）的
    `LLMClient` 临时替换成确定性桩，然后用 `astream(stream_mode="values")` 跑图，
    取最后一份完整状态。

诚实边界（必须明确，否则指标会被误读）：
    意图是由用例注入的，不是模型判出来的。因此本模式**不衡量模型分类能力**，
    它衡量的是"给定意图后，图是否守住了规则"——也就是把模型的不确定性排除掉之后，
    确定性部分是否可靠。依赖模型判断的用例（如"火星签证"该不该拒答）必须标记
    requires_llm 并跳过，绝不能靠桩去"判通过"。

为什么用 stream_mode="values" 而不是 ainvoke 的返回值：
    图的 output_schema 是 GraphOutput，只包含 final_reply / need_handoff /
    handoff_reason / intent / risk_level。而评测需要 flow_path、order_valid、
    order_status 等中间状态。取完整状态流可以拿到真实值，而不是猜。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage

from utils.context import new_context

# 国家白名单：用于从用户消息里抽取"目标国家"。
# 只收录本项目知识库里真实存在的国家/地区，避免把"火星"这类域外词当成有效国家
# 从而产生虚假的"命中知识库"。
KNOWN_COUNTRIES: tuple[str, ...] = (
    "日本",
    "美国",
    "韩国",
    "英国",
    "泰国",
    "澳大利亚",
    "新西兰",
    "加拿大",
    "法国",
    "德国",
    "意大利",
    "西班牙",
    "荷兰",
    "瑞士",
    "瑞典",
    "挪威",
    "丹麦",
    "芬兰",
    "爱尔兰",
    "葡萄牙",
    "希腊",
    "土耳其",
    "埃及",
    "南非",
    "巴西",
    "印度",
    "印度尼西亚",
    "俄罗斯",
    "越南",
    "菲律宾",
    "马来西亚",
    "新加坡",
    "阿联酋",
    "迪拜",
    "申根",
)

# 签证类型关键词 -> 归一化写法
VISA_TYPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("旅游", "旅游"),
    ("商务", "商务"),
    ("学生", "学生"),
    ("留学", "学生"),
    ("工作", "工作"),
    ("探亲", "探亲"),
)

# 规则兜底意图关键词。顺序即优先级：投诉 > 进度 > 材料 > 闲聊 > FAQ。
# 投诉放最前：涉及退款/造假的表述往往同时含"签证""材料"等词，
# 若被归到 faq 会绕过转人工，属于安全相关的错误方向。
_COMPLAINT_KEYWORDS = ("投诉", "退款", "保证出签", "包过", "假材料", "造假", "做假", "骗")
_PROGRESS_KEYWORDS = ("进度", "订单", "办得怎么样", "到哪了", "查一下", "查询")
_MATERIAL_KEYWORDS = ("材料", "清单", "需要什么", "准备什么", "要准备", "缺件")
_CHITCHAT_KEYWORDS = ("你好", "您好", "天气", "谢谢", "哈哈", "在吗", "嗨")

_ORDER_ID_RE = re.compile(r"VISA-\d+", re.IGNORECASE)


def infer_intent(user_message: str) -> str:
    """规则兜底意图分类。

    只在用例没有声明 expect_intent 时使用。它是"够用的规则"而不是"聪明模型"，
    存在的意义是让离线 harness 不依赖任何外部服务即可跑通。
    """
    text = (user_message or "").strip()
    if not text:
        return "chitchat"

    if any(keyword in text for keyword in _COMPLAINT_KEYWORDS):
        return "complaint"
    if any(keyword in text for keyword in _PROGRESS_KEYWORDS):
        return "progress"
    if any(keyword in text for keyword in _MATERIAL_KEYWORDS):
        return "material"
    if any(keyword in text for keyword in _CHITCHAT_KEYWORDS):
        return "chitchat"
    return "faq"


def extract_country(user_message: str) -> str:
    """从消息里抽取国家；抽不到返回空串（交给真实节点去追问）。"""
    text = user_message or ""
    for country in KNOWN_COUNTRIES:
        if country in text:
            return country
    return ""


def extract_visa_type(user_message: str) -> str:
    """从消息里抽取签证类型；抽不到返回空串。"""
    text = user_message or ""
    for keyword, normalized in VISA_TYPE_KEYWORDS:
        if keyword in text:
            return normalized
    return ""


# ========== 桩 LLM ==========

class _ScriptedLLM:
    """把所有 invoke 都返回同一段预设文本的桩。

    刻意不复用真实 LLMClient 的任何逻辑：这样"离线跑通"才真正证明
    "不依赖模型"，而不是"恰好本地有密钥"。
    """

    _payload: str = "{}"

    def __init__(self, ctx: Any = None) -> None:
        self.ctx = ctx

    def invoke(self, messages: Any, **_: Any) -> AIMessage:
        return AIMessage(content=self._payload)

    def stream(self, messages: Any, **_: Any):  # pragma: no cover - 离线路径不使用
        raise NotImplementedError("离线运行器不支持流式调用")


def _make_intent_stub(intent: str, user_message: str) -> type:
    payload = json.dumps(
        {
            "intent": intent,
            "country": extract_country(user_message),
            "visa_type": extract_visa_type(user_message),
            # 订单号交给真实的 order_validate_node 从整句里正则提取，
            # 这样"格式校验"这段生产逻辑在离线模式下也被真实执行。
            "order_id": "",
        },
        ensure_ascii=False,
    )

    class _IntentStub(_ScriptedLLM):
        _payload = payload

    return _IntentStub


def _make_slot_stub() -> type:
    """槽位桩：明确回问国家/签证类型，不假装能从消息里读出不存在的信息。"""
    payload = json.dumps(
        {
            "country": "",
            "visa_type": "",
            "follow_up_message": "请问您计划办理哪个国家的签证？以及是旅游、商务还是学生签证？",
        },
        ensure_ascii=False,
    )

    class _SlotStub(_ScriptedLLM):
        _payload = payload

    return _SlotStub


def _strip_knowledge_markers(text: str) -> str:
    """去掉检索片段里的 【标题】 标记，只留下正文，避免回复像调试日志。"""
    return re.sub(r"【[^】]*】", "", text).strip()


def _build_grounded_reply(state: Any) -> str:
    """按 flow_path 确定性拼装回复。

    设计原则：回复必须"有据可依"——要么来自检索到的知识，要么来自订单查询结果。
    没有依据时明确说"暂未查询到"，而不是编一句像样的话。这样 must_contain /
    must_not_contain 这类文本约束才有意义。
    """
    def field(name: str) -> str:
        value = getattr(state, name, "")
        return value if isinstance(value, str) else ""

    flow_path = field("flow_path") or ("chitchat" if field("intent") == "chitchat" else "normal")

    if flow_path == "handoff":
        reason = field("handoff_reason") or "需人工顾问处理"
        return (
            f"很抱歉，您的情况需要人工协助。已为您转接高级签证顾问，请稍候。\n"
            f"转接原因：{reason}"
        )

    if flow_path == "ask":
        # 追问优先用真实的追问话术，让用户看到的是节点产出的问题。
        questions = [q for q in (field("slot_follow_up"), field("order_follow_up")) if q]
        if questions:
            return "为了给您准确的答复，还需要您补充以下信息：\n" + "\n".join(questions)
        missing = field("missing_slots")
        return f"还需要您补充这些信息：{missing}"

    if flow_path == "confirm":
        prompt = field("confirm_prompt") or "请回复「确认继续」或「转人工」。"
        advice = field("risk_advice")
        return f"{advice}\n\n{prompt}".strip()

    if flow_path == "chitchat":
        return (
            "您好，我是签证客服助手，可以帮您查询各国签证政策、材料清单和订单进度。"
            "请问您想了解哪个国家的签证？"
        )

    knowledge = _strip_knowledge_markers(field("knowledge_context"))
    materials = field("required_materials")
    if knowledge or materials:
        # 截断到前 300 字：离线桩不是模型，不做摘要，只做"引用"，
        # 以保证回复内容确实来自检索结果。
        parts = []
        if knowledge:
            parts.append(f"根据知识库资料：\n{knowledge[:300]}")
        if materials:
            # 材料清单来自节点的结构化输出，单独列出，便于"列缺件"这条能力被验证。
            parts.append(f"所需材料：\n{_render_materials(materials)}")
        return "\n\n".join(parts)

    order_status = field("order_status")
    if order_status:
        return order_status

    return "很抱歉，暂未查询到相关签证信息。建议您访问目的地国家使领馆官网核实最新要求。"


def _render_materials(materials: Any) -> str:
    """渲染材料清单；兼容 list 与已被拼成字符串两种形态。"""
    if isinstance(materials, str):
        return materials
    return "\n".join(f"- {item}" for item in materials)


def _make_reply_stub() -> type:
    """回复桩：返回固定短文本，只用于让节点链路跑通。

    为什么不在这里"扮演模型生成回复"：节点只能拿到 messages，拿不到完整最终状态
    （flow_path / order_status / knowledge_context），一旦让桩去猜，回复就不再
    可验证。因此离线模式下回复文本由图外的 `_build_grounded_reply` 依据最终状态
    确定性拼装——见 run_case_offline 的说明。
    """

    class _ReplyStub(_ScriptedLLM):
        _payload = "（离线模式：回复文本由 harness 依据最终状态拼装）"

    return _ReplyStub


# ========== 运行 ==========

def _read_field(state: Any, name: str, default: Any = "") -> Any:
    """从完整状态里读字段；兼容 pydantic 对象与 dict 两种形态。"""
    if isinstance(state, dict):
        value = state.get(name, default)
    else:
        value = getattr(state, name, default)
    return default if value is None else value


async def _run_graph(payload: Dict[str, Any], intent: str, user_message: str) -> Dict[str, Any]:
    """在补丁生效期间跑图，返回归一化后的结果字典。"""
    from graphs import graph as graph_module  # 延迟导入：避免 import 期就加载 LLM 依赖

    ctx = new_context(method="offline_eval")
    config = {"configurable": {"thread_id": ctx.run_id}}

    last_state: Any = None
    async for chunk in graph_module.main_graph.astream(
        payload,
        config=config,
        context=ctx,
        stream_mode="values",
    ):
        last_state = chunk

    # 回复桩需要"最终状态"，而图跑完才能拿到，因此在图外算好再回填。
    # 这是本 harness 唯一一处"绕过节点"的地方，已在文档中标注。
    return {
        "intent": _read_field(last_state, "intent", intent),
        "flow_path": _read_field(last_state, "flow_path", ""),
        "final_reply": _read_field(last_state, "final_reply", ""),
        "need_handoff": bool(_read_field(last_state, "need_handoff", False)),
        "handoff_reason": _read_field(last_state, "handoff_reason", ""),
        "risk_level": _read_field(last_state, "risk_level", "low"),
        "order_id": _read_field(last_state, "order_id", ""),
        "order_valid": bool(_read_field(last_state, "order_valid", False)),
        "order_status": _read_field(last_state, "order_status", ""),
        "knowledge_context": _read_field(last_state, "knowledge_context", ""),
        "country": _read_field(last_state, "country", ""),
        "visa_type": _read_field(last_state, "visa_type", ""),
        "missing_slots": list(_read_field(last_state, "missing_slots", []) or []),
        "required_materials": list(_read_field(last_state, "required_materials", []) or []),
        # 追问话术必须带出来：离线模式拼装回复时要靠它还原"系统问了什么"，
        # 少了它，ask 路径的回复就会变成一句空话（曾因此漏判 must_contain）。
        "slot_follow_up": _read_field(last_state, "slot_follow_up", ""),
        "order_follow_up": _read_field(last_state, "order_follow_up", ""),
        "confirm_prompt": _read_field(last_state, "confirm_prompt", ""),
        "risk_advice": _read_field(last_state, "risk_advice", ""),
        "complaint_summary": _read_field(last_state, "complaint_summary", ""),
    }


def offline_case_view(case: Dict[str, Any]) -> Dict[str, Any]:
    """离线判定视图：去掉 expect_intent。

    为什么必须去掉：离线模式下，`expect_intent` 被当作"喂给桩的输入"。
    如果同时又拿它当"待验证的期望"，意图准确率就永远是 100%——那是自证，
    不是评测，还会让报告里出现一个漂亮但无意义的数字。

    去掉之后 intent_accuracy 的样本数为 0，报告会显示 n/a，
    读者能立刻明白"离线不评意图分类能力"。
    """
    view = dict(case)
    view.pop("expect_intent", None)
    return view


def run_case_offline(case: Dict[str, Any], intent: Optional[str] = None) -> Dict[str, Any]:
    """离线跑一条用例，返回与 evaluator 对齐的结果字典。

    参数:
        case:   评测集用例；用 expect_intent 作为注入意图（若没有则规则兜底）
        intent: 显式指定注入意图，优先级高于 case

    关于 final_reply：
        response_generate 节点会被真实调用（保证链路完整、不崩），但它拿不到
        "完整最终状态"，所以离线模式下它生成的文本不代表系统能力。真正的回复
        文本由 `_build_grounded_reply` 依据最终状态确定性拼装——规则是"有据可依"：
        有检索就用检索，有订单结果就用订单结果，都没有就说查不到。
        这样 must_contain / must_not_contain 这类文本约束才是有意义的。
    """
    user_message = str(case.get("user_message") or "")
    resolved_intent = intent or case.get("expect_intent") or infer_intent(user_message)

    from graphs.nodes import intent_classify_node, response_generate_node, slot_filling_node

    originals = {
        "intent": intent_classify_node.LLMClient,
        "slot": slot_filling_node.LLMClient,
        "reply": response_generate_node.LLMClient,
    }

    try:
        intent_classify_node.LLMClient = _make_intent_stub(resolved_intent, user_message)
        slot_filling_node.LLMClient = _make_slot_stub()
        response_generate_node.LLMClient = _make_reply_stub()

        payload = {"user_message": user_message}
        result = asyncio.run(_run_graph(payload, resolved_intent, user_message))
    finally:
        # 桩必须用完即还原，否则会污染同一进程里的其他测试。
        intent_classify_node.LLMClient = originals["intent"]
        slot_filling_node.LLMClient = originals["slot"]
        response_generate_node.LLMClient = originals["reply"]

    result["final_reply"] = _build_grounded_reply(_StateView(result))
    return result


class _StateView:
    """把结果字典包装成"像 state 一样可 getattr"的对象，复用拼装逻辑。"""

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        return self._data.get(name, "")
