"""Mock签证订单进度查询插件工具"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Mock订单数据库
MOCK_ORDER_DATABASE: Dict[str, Dict[str, Any]] = {
    "VISA-001001": {
        "order_id": "VISA-001001",
        "country": "日本",
        "visa_type": "旅游签证（3年多次）",
        "status": "审理中",
        "submit_date": "2025-07-20",
        "estimated_days": "5-7个工作日",
        "current_step": "使领馆审理",
        "steps": [
            {"name": "材料提交", "completed": True, "date": "2025-07-20"},
            {"name": "材料审核", "completed": True, "date": "2025-07-22"},
            {"name": "递交使领馆", "completed": True, "date": "2025-07-23"},
            {"name": "使领馆审理", "completed": False, "date": ""},
            {"name": "护照返回", "completed": False, "date": ""},
        ],
    },
    "VISA-001002": {
        "order_id": "VISA-001002",
        "country": "美国",
        "visa_type": "B1/B2商务旅游签证",
        "status": "待面签",
        "submit_date": "2025-08-01",
        "estimated_days": "面签后5-7个工作日",
        "current_step": "等待面签",
        "steps": [
            {"name": "DS-160填写", "completed": True, "date": "2025-07-28"},
            {"name": "缴费并预约", "completed": True, "date": "2025-07-30"},
            {"name": "面签", "completed": False, "date": "预约时间：2025-08-10"},
            {"name": "行政审理", "completed": False, "date": ""},
            {"name": "护照签回", "completed": False, "date": ""},
        ],
    },
    "VISA-001003": {
        "order_id": "VISA-001003",
        "country": "英国",
        "visa_type": "Student Visa学生签证",
        "status": "已出签",
        "submit_date": "2025-06-15",
        "estimated_days": "已完成",
        "current_step": "已完成",
        "steps": [
            {"name": "在线申请", "completed": True, "date": "2025-06-15"},
            {"name": "生物信息采集", "completed": True, "date": "2025-06-18"},
            {"name": "材料递交", "completed": True, "date": "2025-06-19"},
            {"name": "使领馆审理", "completed": True, "date": "2025-07-05"},
            {"name": "签证获批", "completed": True, "date": "2025-07-10"},
        ],
    },
    "VISA-001004": {
        "order_id": "VISA-001004",
        "country": "泰国",
        "visa_type": "旅游签证",
        "status": "材料补充中",
        "submit_date": "2025-08-05",
        "estimated_days": "材料补齐后3-5个工作日",
        "current_step": "等待补充材料",
        "steps": [
            {"name": "材料提交", "completed": True, "date": "2025-08-05"},
            {"name": "材料审核", "completed": False, "date": "需补充：近6个月银行流水"},
            {"name": "递交使领馆", "completed": False, "date": ""},
            {"name": "签证审理", "completed": False, "date": ""},
            {"name": "护照返回", "completed": False, "date": ""},
        ],
    },
    "VISA-001005": {
        "order_id": "VISA-001005",
        "country": "澳大利亚",
        "visa_type": "600类旅游签证",
        "status": "已拒签",
        "submit_date": "2025-05-10",
        "estimated_days": "已结束",
        "current_step": "已拒签",
        "steps": [
            {"name": "在线申请", "completed": True, "date": "2025-05-10"},
            {"name": "材料上传", "completed": True, "date": "2025-05-12"},
            {"name": "审理", "completed": True, "date": "2025-06-01"},
            {"name": "拒签通知", "completed": True, "date": "2025-06-05"},
        ],
    },
}


def query_order_progress(order_id: str) -> Dict[str, Any]:
    """
    Mock查进度插件：根据订单号查询签证办理进度

    Args:
        order_id: 签证订单号，格式如 VISA-001001

    Returns:
        包含订单状态信息的字典，未找到时返回错误信息
    """
    if not order_id or not isinstance(order_id, str):
        return {
            "found": False,
            "message": "订单号不能为空"
        }

    order_id = order_id.strip().upper()
    order = MOCK_ORDER_DATABASE.get(order_id)

    if order is None:
        logger.warning(f"未找到订单: order_id={order_id}")
        available_ids = ", ".join(MOCK_ORDER_DATABASE.keys())
        return {
            "found": False,
            "message": f"未找到订单号为 {order_id} 的签证订单。可用的测试订单号：{available_ids}"
        }

    logger.info(f"成功查询订单: order_id={order_id}, status={order.get('status')}")
    result = dict(order)
    result["found"] = True
    return result
