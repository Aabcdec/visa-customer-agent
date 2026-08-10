"""风险门控节点 - 全链路赋值 flow_path；高风险转人工；中风险走确认"""
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import RiskAssessmentInput, RiskAssessmentOutput

logger = logging.getLogger(__name__)

# 高风险：必须转人工（不含单纯「加急」，加急走确认）
HIGH_RISK_KEYWORDS = [
    "拒签", "遣返", "非法滞留", "造假", "假材料", "黑名单",
    "敏感", "军事", "情报", "政治",
    "保证出签", "保证通过", "一定能过", "保证签过", "包过",
    "做假", "办假", "伪造", "翻案包过",
]

# 中风险：加强提示 + 用户确认后再继续（含时效/加急类）
MEDIUM_RISK_KEYWORDS = [
    "自由职业", "刚入职", "没有工作", "第一次出国",
    "无房", "无车", "存款不够", "余额不足",
    "被拒过", "之前拒签",
    "加急", "明天出发", "后天出发", "三天内", "紧急",
    "明天出结果", "今天出签",
]


def risk_assessment_node(
    state: RiskAssessmentInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> RiskAssessmentOutput:
    """
    title: 风险门控
    desc: 关键词评估风险等级；高风险/上游投诉→handoff；中风险→confirm确认草案；缺槽位/缺订单号→ask；否则normal。统一写出flow_path供回复生成消费。
    """
    _ = runtime.context

    user_msg = (state.user_message or "").lower()
    knowledge_ctx = (state.knowledge_context or "").lower()
    combined_text = f"{user_msg} {knowledge_ctx}"

    risk_level = "low"
    risk_advice_parts = []
    need_handoff = bool(state.need_handoff)
    handoff_reason = state.handoff_reason or ""
    need_confirm = False
    confirm_prompt = ""

    high_risk_hits = [kw for kw in HIGH_RISK_KEYWORDS if kw in combined_text]
    if high_risk_hits:
        risk_level = "high"
        risk_advice_parts.append(f"检测到高风险因素：{', '.join(high_risk_hits)}")
        need_handoff = True
        if not handoff_reason:
            handoff_reason = (
                f"用户情况涉及高风险因素（{', '.join(high_risk_hits)}），"
                "建议由专业签证顾问提供个性化指导"
            )

    if risk_level != "high":
        medium_risk_hits = [kw for kw in MEDIUM_RISK_KEYWORDS if kw in combined_text]
        if medium_risk_hits:
            risk_level = "medium"
            risk_advice_parts.append(f"检测到中等风险/时效诉求：{', '.join(medium_risk_hits)}")
            risk_advice_parts.append("无法承诺加急必出或出签结果，需您确认是否按常规评估继续")

    if risk_level == "low":
        risk_advice = "当前情况属于低风险，材料准备齐全即可按正常流程申请。建议提前1-2个月递交申请。"
    elif risk_level == "medium":
        risk_advice = "；".join(risk_advice_parts) + "。"
        need_confirm = True
        confirm_prompt = (
            "【需您确认】根据当前信息，我可以继续给出材料/政策参考，"
            "但无法承诺加急时效或出签结果。"
            "回复「确认继续」我将按常规口径说明；回复「转人工」可为您接通顾问。"
        )
    else:
        risk_advice = "；".join(risk_advice_parts) + "。强烈建议转人工获取个性化指导。"

    # flow_path 优先级：handoff > ask > confirm > normal
    has_ask = bool(state.missing_slots) or bool(state.order_follow_up) or bool(state.slot_follow_up)
    if need_handoff:
        flow_path = "handoff"
        need_confirm = False
        confirm_prompt = ""
    elif has_ask:
        flow_path = "ask"
        # 追问优先；确认提示可附在 advice，但不改路径为 confirm
        need_confirm = False
    elif need_confirm:
        flow_path = "confirm"
    else:
        flow_path = "normal"

    logger.info(
        "风险评估完成: risk_level=%s, flow_path=%s, need_handoff=%s, need_confirm=%s",
        risk_level,
        flow_path,
        need_handoff,
        need_confirm,
    )

    return RiskAssessmentOutput(
        risk_level=risk_level,
        risk_advice=risk_advice,
        need_handoff=need_handoff,
        handoff_reason=handoff_reason,
        need_confirm=need_confirm,
        confirm_prompt=confirm_prompt,
        flow_path=flow_path,
    )
