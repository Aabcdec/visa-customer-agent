"""回复生成节点 - 强制只依据检索/插件结果，禁止瞎编"""
import json
from pathlib import Path
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from utils.context import Context
from utils.llm import LLMClient
from graphs.state import ResponseGenerateInput, ResponseGenerateOutput
from utils.llm_messages import build_chat_messages, ensure_text, get_text_content

# 项目根目录（src/graphs/nodes/ -> projects/）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def response_generate_node(
    state: ResponseGenerateInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> ResponseGenerateOutput:
    """
    title: 回复生成
    desc: 按 flow_path（ask/confirm/normal/handoff/chitchat）生成回复；只依据知识库/插件结果；支持中风险确认问句与转人工提示。
    integrations: 大语言模型
    """
    ctx = runtime.context

    cfg_file = PROJECT_ROOT / config["metadata"]["llm_cfg"]
    with open(cfg_file, "r", encoding="utf-8") as fd:
        llm_cfg = json.load(fd)

    llm_config = llm_cfg.get("config", {})
    sp = llm_cfg.get("sp", "")
    up_template = llm_cfg.get("up", "")

    missing_slots_str = "、".join(state.missing_slots) if state.missing_slots else "无"

    # 闲聊直达时若未写路径，兜底
    flow_path = state.flow_path or ("chitchat" if state.intent == "chitchat" else "normal")

    handoff_notice = ""
    if state.need_handoff or flow_path == "handoff":
        handoff_notice = (
            f"\n\n【转人工提示】原因：{state.handoff_reason or '需人工顾问处理'}。"
            "请在回复末尾告知用户：已为您转接高级签证顾问，请稍候。"
        )

    confirm_notice = ""
    if state.need_confirm or flow_path == "confirm":
        confirm_notice = (
            "\n\n【确认节点】必须先给出简要说明，再原样附上确认问句，"
            "不得承诺出签或加急必成。\n"
            f"确认问句：{state.confirm_prompt or '请回复「确认继续」或「转人工」。'}"
        )

    knowledge_context = state.knowledge_context
    if not knowledge_context:
        knowledge_context = "（知识库未返回相关信息）"
    else:
        knowledge_context = ensure_text(knowledge_context)

    up_tpl = Template(up_template)
    user_prompt = up_tpl.render(
        user_message=ensure_text(state.user_message),
        intent=ensure_text(state.intent),
        country=ensure_text(state.country),
        visa_type=ensure_text(state.visa_type),
        knowledge_context=knowledge_context,
        order_status=ensure_text(state.order_status) if state.order_status else "（无）",
        risk_level=ensure_text(state.risk_level),
        risk_advice=ensure_text(state.risk_advice),
        missing_slots=missing_slots_str,
        slot_follow_up=ensure_text(state.slot_follow_up),
        flow_path=ensure_text(flow_path),
        order_follow_up=ensure_text(state.order_follow_up),
        complaint_summary=ensure_text(state.complaint_summary),
        handoff_notice=handoff_notice,
        confirm_notice=confirm_notice,
        confirm_prompt=ensure_text(state.confirm_prompt),
    )

    client = LLMClient(ctx=ctx)
    messages = build_chat_messages(sp, user_prompt)

    model_id = llm_config.get("model", "doubao-seed-2-0-mini-260215")
    temperature = llm_config.get("temperature", 0.3)
    max_tokens = llm_config.get("max_completion_tokens", 2000)

    response = client.invoke(
        messages=messages,
        model=model_id,
        temperature=temperature,
        top_p=llm_config.get("top_p", 0.7),
        max_completion_tokens=max_tokens
    )

    final_reply = get_text_content(response.content)
    return ResponseGenerateOutput(final_reply=final_reply)
