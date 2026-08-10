"""订单进度查询节点 - 已验证订单号查询，查无/失败有兜底话术"""
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from tools.order_progress_tool import query_order_progress
from graphs.state import OrderProgressInput, OrderProgressOutput

logger = logging.getLogger(__name__)


def order_progress_query_node(
    state: OrderProgressInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> OrderProgressOutput:
    """
    title: 订单进度查询
    desc: 通过Mock查进度插件，根据已验证的签证订单号查询当前办理进度。查无结果或插件失败时返回兜底话术，绝不编造进度信息。
    """
    ctx = runtime.context

    order_id = state.order_id.strip()

    if not order_id:
        return OrderProgressOutput(
            order_status="未提供有效的订单号，请提供您的签证订单号。订单号格式通常为：VISA-XXXXXX"
        )

    try:
        result = query_order_progress(order_id)

        if not isinstance(result, dict):
            logger.error(f"插件返回非字典类型: {type(result)}")
            return OrderProgressOutput(
                order_status=f"查询系统暂时异常，请稍后重试或联系人工客服查询订单 {order_id} 的进度。"
            )

        if result.get("found", False):
            status_info = result.get("status", "未知")
            country = result.get("country", "未知")
            visa_type = result.get("visa_type", "未知")
            estimated_days = result.get("estimated_days", "未知")
            submit_date = result.get("submit_date", "未知")
            current_step = result.get("current_step", "未知")
            steps = result.get("steps", [])

            # 构建详细状态描述
            steps_desc = "\n".join(
                f"  {'✅' if s.get('completed') else '⏳'} {s.get('name', '')}"
                + (f" ({s.get('date', '')})" if s.get('completed') else "")
                for s in steps
            )

            order_status = (
                f"订单号：{order_id}\n"
                f"目的地：{country} - {visa_type}\n"
                f"递交日期：{submit_date}\n"
                f"当前状态：{status_info}\n"
                f"当前环节：{current_step}\n"
                f"预计处理时间：{estimated_days}\n"
                f"办理进度：\n{steps_desc}"
            )
        else:
            # 查无结果：使用兜底话术，不编造进度
            error_msg = result.get("message", "未找到该订单")
            order_status = (
                f"很抱歉，{error_msg}。\n"
                f"请确认订单号是否正确。如订单号无误但仍无法查询，建议联系人工客服协助处理。"
            )

    except Exception as e:
        # 插件异常：兜底话术
        logger.error(f"订单进度查询异常: order_id={order_id}, error={str(e)}")
        order_status = (
            f"查询订单 {order_id} 进度时系统出现异常，请稍后重试。\n"
            f"如持续无法查询，建议联系人工客服并提供您的订单号。"
        )

    return OrderProgressOutput(order_status=order_status)
