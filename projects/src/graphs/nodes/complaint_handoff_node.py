"""投诉转人工节点 - 固定话术+摘要，不经模型软劝"""
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from utils.context import Context
from graphs.state import ComplaintHandoffInput, ComplaintHandoffOutput

logger = logging.getLogger(__name__)

# 投诉类关键词映射
COMPLAINT_KEYWORDS = {
    "保证出签": "用户要求保证出签结果",
    "退款": "用户要求退款",
    "投诉": "用户提出投诉",
    "造假": "用户涉及材料造假请求",
    "假材料": "用户涉及材料造假请求",
    "做假": "用户涉及材料造假请求",
    "加急保证": "用户要求加急并保证通过",
}


def complaint_handoff_node(
    state: ComplaintHandoffInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> ComplaintHandoffOutput:
    """
    title: 投诉转人工
    desc: 处理投诉、退款、保证出签、造假请求等敏感场景。使用固定转人工话术+结构化摘要（意图+国家+原因），不依赖模型生成回复，避免翻车。
    """
    ctx = runtime.context

    user_msg = state.user_message
    country = state.country if state.country else "未提供"

    # 识别具体投诉原因
    detected_reasons = []
    msg_lower = user_msg.lower()
    for keyword, reason_desc in COMPLAINT_KEYWORDS.items():
        if keyword in msg_lower:
            if reason_desc not in detected_reasons:
                detected_reasons.append(reason_desc)

    # 兜底：如果没匹配到关键词，使用通用描述
    if not detected_reasons:
        detected_reasons.append("用户提出特殊诉求")

    reason_str = "；".join(detected_reasons)

    # 构建结构化摘要
    summary_parts = [
        "【客户诉求摘要】",
        f"意图类型：{state.intent}",
        f"涉及国家：{country}",
        f"转接原因：{reason_str}",
        f"用户原话：{user_msg[:200]}"
    ]
    complaint_summary = "\n".join(summary_parts)

    handoff_reason = f"{reason_str}，需人工客服介入处理"

    logger.info(
        f"投诉转人工触发: intent={state.intent}, country={country}, "
        f"reasons={detected_reasons}"
    )

    return ComplaintHandoffOutput(
        need_handoff=True,
        handoff_reason=handoff_reason,
        complaint_summary=complaint_summary,
        flow_path="handoff"
    )
