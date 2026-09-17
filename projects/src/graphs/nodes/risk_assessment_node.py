"""风险门控节点 - 全链路赋值 flow_path；高风险转人工；中风险走确认"""
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from utils.context import Context
from graphs.state import RiskAssessmentInput, RiskAssessmentOutput

logger = logging.getLogger(__name__)

# 高风险：必须转人工。
#
# 判定标准是"真实的违规、失信或违规请求"，而不是"听起来敏感"。
# 特别注意：「拒签」**不在**这里。被拒签是常见且合法的再申请场景，
# 把它归为高风险会导致人工坐席被可自动处理的咨询淹没，
# 因此它归入下面的中风险（加强提示 + 用户确认）。
HIGH_RISK_KEYWORDS = [
    "遣返", "非法滞留", "造假", "假材料", "黑名单",
    "敏感", "军事", "情报", "政治",
    "保证出签", "保证通过", "一定能过", "保证签过", "包过",
    "做假", "办假", "伪造", "翻案包过",
]

# 中风险：加强提示 + 用户确认后再继续（含时效/加急类，以及被拒签的再申请）
MEDIUM_RISK_KEYWORDS = [
    "自由职业", "刚入职", "没有工作", "第一次出国",
    "无房", "无车", "存款不够", "余额不足",
    # 拒签类：裸关键词即可覆盖"拒签过/被拒签/拒签记录/之前拒签"等说法，
    # 避免因措辞差异漏判（原先只写"之前拒签"，反而被高风险的同名关键词吃掉）。
    "拒签", "被拒过",
    "加急", "明天出发", "后天出发", "三天内", "紧急",
    "明天出结果", "今天出签",
]

# 合规红线：客服话术不得复述"保证/包过"类承诺措辞。
# 即便本意是"我们不能保证"，把该措辞原样写进回复仍可能被截图后误读为承诺，
# 所以对外话术统一换成中性描述；关键词匹配本身仍按原文，不影响判定。
_PROMISE_KEYWORDS = frozenset(
    {"保证出签", "保证通过", "一定能过", "保证签过", "包过", "翻案包过"}
)
_NEUTRAL_PROMISE_LABEL = "用户要求对出签结果作出承诺"


def _describe_hits(hits: list) -> list:
    """把命中的关键词转成可对外的话术标签（承诺类做中性化替换）。"""
    labels: list = []
    for keyword in hits:
        label = _NEUTRAL_PROMISE_LABEL if keyword in _PROMISE_KEYWORDS else keyword
        if label not in labels:
            labels.append(label)
    return labels


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
    # 只在"用户自己的话"里找风险信号。
    #
    # 为什么不能拼接 knowledge_context：检索到的政策原文里天然会写"拒签后可否重新申请"
    # "自由职业者材料"这类字眼，那是文档在描述规则，不代表这位用户存在该风险。
    # 曾经把知识库正文一起扫进来，结果"日本旅游签证要办多久"这种正常提问被判 high
    # 并转人工。风险信号必须只来自用户陈述。
    combined_text = user_msg

    risk_level = "low"
    risk_advice_parts = []
    need_handoff = bool(state.need_handoff)
    handoff_reason = state.handoff_reason or ""
    need_confirm = False
    confirm_prompt = ""

    high_risk_hits = [kw for kw in HIGH_RISK_KEYWORDS if kw in combined_text]
    if high_risk_hits:
        risk_level = "high"
        risk_labels = _describe_hits(high_risk_hits)
        risk_advice_parts.append(f"检测到高风险因素：{', '.join(risk_labels)}")
        need_handoff = True
        if not handoff_reason:
            handoff_reason = (
                f"用户情况涉及高风险因素（{', '.join(risk_labels)}），"
                "建议由专业签证顾问提供个性化指导"
            )

    if risk_level != "high":
        medium_risk_hits = [kw for kw in MEDIUM_RISK_KEYWORDS if kw in combined_text]
        if medium_risk_hits:
            risk_level = "medium"
            risk_labels = _describe_hits(medium_risk_hits)
            risk_advice_parts.append(f"检测到中等风险/时效诉求：{', '.join(risk_labels)}")
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
    #
    # 注意：has_ask 只看"真正缺失的必填槽位"和两类追问话术。
    # 绝不能把 required_materials（所需材料清单）算进来——它是给模型看的参考资料，
    # 不等于"还缺用户信息"。曾因共用一个字段，导致用户问"要什么材料"时被反问回去。
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
