"""意图分类节点 - 使用LLM对用户消息进行意图分类和信息提取"""
import os
import json
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from coze_coding_dev_sdk import LLMClient
from graphs.state import IntentClassifyInput, IntentClassifyOutput
from utils.llm_messages import build_chat_messages, ensure_text, get_text_content


def intent_classify_node(
    state: IntentClassifyInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> IntentClassifyOutput:
    """
    title: LLM意图分类
    desc: 使用大语言模型对用户消息进行意图分类，同时提取国家、签证类型、订单号等关键信息。支持5种意图：faq、material、progress、complaint、chitchat。
    integrations: 大语言模型
    """
    ctx = runtime.context

    # 读取LLM配置
    workspace_path = os.getenv("COZE_WORKSPACE_PATH", "")
    cfg_file = os.path.join(workspace_path, config["metadata"]["llm_cfg"])
    with open(cfg_file, "r", encoding="utf-8") as fd:
        llm_cfg = json.load(fd)

    llm_config = llm_cfg.get("config", {})
    sp = llm_cfg.get("sp", "")
    up_template = llm_cfg.get("up", "")

    # 渲染用户提示词模板（user_message 强制文本，避免对象进模板）
    up_tpl = Template(up_template)
    user_prompt = up_tpl.render(user_message=ensure_text(state.user_message))

    client = LLMClient(ctx=ctx)
    # 必须用 role/content dict；不要用带 name 的 LangChain Message
    messages = build_chat_messages(sp, user_prompt)

    model_id = llm_config.get("model", "doubao-seed-2-0-mini-260215")
    temperature = llm_config.get("temperature", 0.1)
    max_tokens = llm_config.get("max_completion_tokens", 1000)

    response = client.invoke(
        messages=messages,
        model=model_id,
        temperature=temperature,
        max_completion_tokens=max_tokens
    )

    raw_content = get_text_content(response.content)

    # 解析LLM返回的JSON
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
        # 解析失败时，默认归类为闲聊，避免误入业务分支
        result = {
            "intent": "chitchat",
            "country": "",
            "visa_type": "",
            "order_id": ""
        }

    intent = result.get("intent", "chitchat")
    country = result.get("country", "") or ""
    visa_type = result.get("visa_type", "") or ""
    order_id = result.get("order_id", "") or ""

    # 与 graph 路由、llm_cfg 保持同一套枚举
    valid_intents = ["faq", "material", "progress", "complaint", "chitchat"]
    if intent not in valid_intents:
        intent = "chitchat"

    return IntentClassifyOutput(
        intent=intent,
        country=country,
        visa_type=visa_type,
        order_id=order_id,
        # 闲聊直达回复生成，跳过风控，必须在此写上路径
        flow_path="chitchat" if intent == "chitchat" else "",
    )
