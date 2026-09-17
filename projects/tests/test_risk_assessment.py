"""风控门控节点测试。

这是整条链路里最需要保护的一段：它决定"谁必须转人工"和"谁需要二次确认"。
判错的代价是不对称的——
    - 漏判高风险（把造假请求当普通咨询答下去）是合规事故；
    - 误判高风险（把正常提问转人工）会让真人客服被无谓请求淹没。
所以下面两个方向都有测试。

flow_path 优先级（生产代码注释里声明的契约）：handoff > ask > confirm > normal
"""
from __future__ import annotations

import pytest

from graphs.nodes.risk_assessment_node import risk_assessment_node
from graphs.state import RiskAssessmentInput


def _run(fake_runtime, **overrides):
    """构造输入并调用节点；只传测试关心的字段。"""
    state = RiskAssessmentInput(**overrides)
    return risk_assessment_node(state, {}, fake_runtime)


# ========== 高风险：必须转人工 ==========

@pytest.mark.parametrize(
    "message",
    [
        "帮我做假流水可以吗",
        "我想伪造一份在职证明",
        "你能保证出签吗",
        "我这个算包过吗",
        "我之前被遣返过，还能办吗",
    ],
)
def test_high_risk_keywords_force_handoff(fake_runtime, message: str) -> None:
    result = _run(fake_runtime, user_message=message, intent="faq")

    assert result.risk_level == "high"
    assert result.need_handoff is True
    assert result.flow_path == "handoff"


def test_high_risk_reply_must_not_contain_promise(fake_runtime) -> None:
    """高风险建议里不能出现任何"保证"类承诺，这是合规红线。"""
    result = _run(fake_runtime, user_message="能保证我一定能过吗", intent="faq")

    assert "保证出签" not in result.risk_advice
    assert "一定能过" not in result.risk_advice


def test_high_risk_overrides_medium_confirm(fake_runtime) -> None:
    """同时出现中风险词时，仍必须以高风险为准，不能降级成 confirm。"""
    result = _run(
        fake_runtime,
        user_message="我是自由职业，存款不够，能帮我做假材料吗",
        intent="faq",
    )

    assert result.risk_level == "high"
    assert result.flow_path == "handoff"
    assert result.need_confirm is False


# ========== 回归：知识库正文不得触发风控升级 ==========

def test_retrieved_knowledge_text_does_not_escalate_risk(fake_runtime) -> None:
    """回归测试：政策原文里出现"拒签"等词，不得把正常提问判成高风险。

    背景：这曾是一个真实缺陷。风控原先把 knowledge_context（检索到的政策正文）
    也纳入关键词扫描，而日本签证 FAQ 里本来就有"拒签后是否可以重新申请"这句话，
    导致"日本旅游签证要办多久"这种完全正常的问题被判 high 并转人工。
    政策文档提到某个词，不等于这位用户存在该风险——风险信号只能来自用户自身。
    """
    policy_text = (
        "【日本签证】\n- 办理周期：5-7个工作日\n"
        "- 拒签后是否可以重新申请：可以，建议间隔3个月以上\n"
        "- 敏感地区申请人需提供额外材料"
    )

    result = _run(
        fake_runtime,
        user_message="日本旅游签证一般要办多久？",
        intent="faq",
        country="日本",
        knowledge_context=policy_text,
    )

    assert result.risk_level == "low"
    assert result.flow_path == "normal"
    assert result.need_handoff is False


def test_retrieved_knowledge_text_does_not_trigger_confirm(fake_runtime) -> None:
    """同理，材料清单里的"自由职业者"章节也不该让用户进入确认流程。"""
    checklist = "### 自由职业者\n1. 收入证明\n2. 资产证明"

    result = _run(
        fake_runtime,
        user_message="英国旅游签证要准备什么材料？",
        intent="material",
        country="英国",
        visa_type="旅游",
        knowledge_context=checklist,
    )

    assert result.risk_level == "low"
    assert result.flow_path == "normal"


# ========== 中风险：需确认 ==========

def test_medium_risk_requires_confirmation(fake_runtime) -> None:
    result = _run(fake_runtime, user_message="我是自由职业，办日本签证好办吗", intent="faq")

    assert result.risk_level == "medium"
    assert result.need_confirm is True
    assert result.flow_path == "confirm"
    assert result.confirm_prompt


@pytest.mark.xfail(
    strict=True,
    reason=(
        "策略冲突（待产品决策）：「拒签」同时在 HIGH_RISK_KEYWORDS 和 "
        "MEDIUM_RISK_KEYWORDS（'之前拒签'）里，且高风险优先，"
        "导致中风险的'之前拒签'永远不可能命中。"
        "被拒签是常见且合法的再申请场景，若一律转人工会淹没人工客服；"
        "但它也确实需要更谨慎的处理。需业务方确认归到哪一档。"
    ),
)
def test_previous_rejection_is_treated_as_medium_risk(fake_runtime) -> None:
    """被拒签后重新申请，按 MEDIUM_RISK_KEYWORDS 的意图应走 confirm。"""
    result = _run(fake_runtime, user_message="我之前拒签过，现在想再办日本签证", intent="faq")

    assert result.risk_level == "medium"
    assert result.flow_path == "confirm"


def test_rejected_before_phrasing_is_medium(fake_runtime) -> None:
    """用「被拒过」措辞时能正确落到中风险——说明中风险规则本身是有效的。"""
    result = _run(fake_runtime, user_message="我之前被拒过，还想再试试日本签证", intent="faq")

    assert result.risk_level == "medium"
    assert result.flow_path == "confirm"


def test_urgent_request_is_medium_not_high(fake_runtime) -> None:
    """加急属于"不能承诺"而不是"违规"，按生产代码契约走确认而不是转人工。"""
    result = _run(fake_runtime, user_message="我明天出发，能加急办出来吗", intent="faq")

    assert result.risk_level == "medium"
    assert result.flow_path == "confirm"


def test_confirm_prompt_forbids_promising_deadline(fake_runtime) -> None:
    result = _run(fake_runtime, user_message="我明天出发，能加急吗", intent="faq")

    assert "无法承诺" in result.confirm_prompt


# ========== 低风险 ==========

def test_plain_question_stays_normal(fake_runtime) -> None:
    result = _run(fake_runtime, user_message="日本旅游签证要办多久？", intent="faq", country="日本")

    assert result.risk_level == "low"
    assert result.flow_path == "normal"
    assert result.need_confirm is False
    assert result.need_handoff is False


# ========== flow_path 优先级 ==========

def test_ask_overrides_confirm_when_slots_missing(fake_runtime) -> None:
    """缺信息时先追问，不应同时把用户按在"确认"状态上。"""
    result = _run(
        fake_runtime,
        user_message="我是自由职业，想办签证",
        intent="material",
        missing_slots=["country"],
    )

    assert result.flow_path == "ask"
    assert result.need_confirm is False


def test_handoff_overrides_ask(fake_runtime) -> None:
    """高风险必须压过追问：先把人转出去，不能卡在补槽位上。"""
    result = _run(
        fake_runtime,
        user_message="用假材料会被发现吗",
        intent="material",
        missing_slots=["country"],
    )

    assert result.flow_path == "handoff"
    assert result.need_handoff is True


def test_upstream_handoff_flag_is_preserved(fake_runtime) -> None:
    """投诉节点已经标记转人工时，风控不能把它清掉。"""
    result = _run(
        fake_runtime,
        user_message="我要投诉",
        intent="complaint",
        need_handoff=True,
        handoff_reason="用户提出投诉",
    )

    assert result.flow_path == "handoff"
    assert result.need_handoff is True
    assert result.handoff_reason == "用户提出投诉"


def test_order_follow_up_routes_to_ask(fake_runtime) -> None:
    result = _run(
        fake_runtime,
        user_message="我的签证进度",
        intent="progress",
        order_follow_up="请提供订单号",
    )

    assert result.flow_path == "ask"
