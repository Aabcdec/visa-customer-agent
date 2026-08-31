"""槽位填充节点 - material意图先槽位后检索，提取国家/签证类型"""
import json
from pathlib import Path
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from utils.context import Context
from utils.llm import LLMClient
from graphs.state import SlotFillingInput, SlotFillingOutput
from utils.llm_messages import build_chat_messages, ensure_text, get_text_content

# 项目根目录（src/graphs/nodes/ -> projects/）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def slot_filling_node(
    state: SlotFillingInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> SlotFillingOutput:
    """
    title: 槽位填充
    desc: 检查当前对话中是否已收集到足够的关键信息。material意图优先提取国家+签证类型（先槽位后检索）；faq意图提取国家；progress意图提取订单号。如有缺失则通过LLM尝试补充，或生成追问话术。
    integrations: 大语言模型
    """
    ctx = runtime.context

    cfg_file = PROJECT_ROOT / config["metadata"]["llm_cfg"]
    with open(cfg_file, "r", encoding="utf-8") as fd:
        llm_cfg = json.load(fd)

    llm_config = llm_cfg.get("config", {})
    sp = llm_cfg.get("sp", "")
    up_template = llm_cfg.get("up", "")

    required_slots_map = {
        "faq": ["country"],
        "material": ["country", "visa_type"],
        "progress": [],
        "chitchat": [],
        "complaint": [],
    }
    required_slots = required_slots_map.get(state.intent, [])

    filled_slots = {}
    if state.country:
        filled_slots["country"] = state.country
    if state.visa_type:
        filled_slots["visa_type"] = state.visa_type

    missing = [s for s in required_slots if s not in filled_slots]

    if missing:
        up_tpl = Template(up_template)
        user_prompt = up_tpl.render(
            user_message=ensure_text(state.user_message),
            intent=ensure_text(state.intent),
            country=ensure_text(state.country),
            visa_type=ensure_text(state.visa_type),
            missing_slots=", ".join(missing)
        )

        client = LLMClient(ctx=ctx)
        messages = build_chat_messages(sp, user_prompt)

        model_id = llm_config.get("model", "doubao-seed-2-0-mini-260215")
        temperature = llm_config.get("temperature", 0.1)
        max_tokens = llm_config.get("max_completion_tokens", 1000)

        response = client.invoke(
            messages=messages,
            model=model_id,
            temperature=temperature,
            top_p=llm_config.get("top_p", 0.7),
            max_completion_tokens=max_tokens
        )

        raw_content = get_text_content(response.content)

        try:
            content_str = raw_content.strip()
            if content_str.startswith("```"):
                lines = content_str.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.strip().startswith("```") and not in_block:
                        in_block = True
                        continue
                    elif line.strip().startswith("```") and in_block:
                        break
                    elif in_block:
                        json_lines.append(line)
                content_str = "\n".join(json_lines)
            result = json.loads(content_str)
        except (json.JSONDecodeError, ValueError):
            result = {}

        extracted_country = result.get("country", state.country) or ""
        extracted_visa_type = result.get("visa_type", state.visa_type) or ""
        follow_up_message = result.get("follow_up_message", "") or ""

        still_missing = []
        if "country" in required_slots and not extracted_country:
            still_missing.append("country")
        if "visa_type" in required_slots and not extracted_visa_type:
            still_missing.append("visa_type")

        return SlotFillingOutput(
            country=extracted_country,
            visa_type=extracted_visa_type,
            missing_slots=still_missing,
            slot_follow_up=follow_up_message
        )

    return SlotFillingOutput(
        country=state.country,
        visa_type=state.visa_type,
        missing_slots=[],
        slot_follow_up=""
    )
