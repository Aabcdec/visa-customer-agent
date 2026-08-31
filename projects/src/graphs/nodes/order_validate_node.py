"""订单号验证节点 - 从整句提取 VISA-数字，无号追问，不编进度"""
import re
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from utils.context import Context
from graphs.state import OrderValidateInput, OrderValidateOutput

logger = logging.getLogger(__name__)

# 整句中提取（不要用 ^$ 绑死整句）
ORDER_ID_EXTRACT = re.compile(r"VISA-\d+", re.IGNORECASE)
# 已提取值的格式校验
ORDER_ID_FULL = re.compile(r"^VISA-\d+$", re.IGNORECASE)


def _extract_order_id(text: str) -> str:
    if not text:
        return ""
    match = ORDER_ID_EXTRACT.search(text)
    return match.group(0).upper() if match else ""


def order_validate_node(
    state: OrderValidateInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> OrderValidateOutput:
    """
    title: 订单号验证
    desc: 从订单号字段或用户整句中提取 VISA-XXXXXX；无号追问；格式错误提示；通过后才查进度。
    """
    _ = runtime.context

    order_id = (state.order_id or "").strip()
    if order_id:
        extracted = _extract_order_id(order_id)
        order_id = extracted or order_id.strip().upper()
    else:
        order_id = _extract_order_id(state.user_message or "")
        if order_id:
            logger.info("从消息中提取到订单号: %s", order_id)

    if not order_id:
        logger.info("未提供订单号，需要追问")
        return OrderValidateOutput(
            order_id="",
            order_valid=False,
            order_follow_up=(
                "请问您的签证订单号是多少？"
                "订单号格式通常为 VISA-XXXXXX（如 VISA-001001），"
                "您可以在签证申请确认邮件中找到。"
            ),
        )

    if not ORDER_ID_FULL.match(order_id):
        logger.warning("订单号格式不正确: %s", order_id)
        return OrderValidateOutput(
            order_id=order_id,
            order_valid=False,
            order_follow_up=(
                f"您提供的订单号「{order_id}」格式似乎不正确。"
                "正确的格式为 VISA-XXXXXX（如 VISA-001001），请确认后重新提供。"
            ),
        )

    logger.info("订单号验证通过: %s", order_id)
    return OrderValidateOutput(
        order_id=order_id.upper(),
        order_valid=True,
        order_follow_up="",
    )
