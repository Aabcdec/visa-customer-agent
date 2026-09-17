"""判定器（evaluator）的测试——先写测试，再写实现。

设计意图：
    旧 eval/run.py 只打印 Y/N，不计算指标、不返回失败码，所以"评测通过"这件事
    无法写进 CI。这里的判定器要解决三件事：
    1. 每条用例给出可解释的通过/失败原因（不是只打印一行 Y/N）；
    2. 把 60+ 条用例汇总成可比较的指标（准确率 / 精确率 / 召回率）；
    3. 指标低于阈值时能明确告诉调用方"哪几个指标挂了"，供退出码使用。

指标口径（必须和文档一致，否则数字会被误读）：
    - refusal 视为"正类"：预测为正 = 系统拒答/转人工；真实为正 = 用例期望拒答。
    - 没有任何预测为正时，precision 无定义，返回 None 而不是 0.0——
      0.0 会被误读成"精确率极差"，None 才是"无法计算"。
"""
from __future__ import annotations

from eval.evaluator import (
    CaseResult,
    CheckOutcome,
    aggregate,
    detect_cites_retrieval,
    detect_refusal,
    evaluate_case,
    gate,
    render_markdown,
)


# ========== 拒答识别 ==========

def test_detect_refusal_true_when_handoff_flag_set() -> None:
    assert detect_refusal({"need_handoff": True, "final_reply": "已为您转接顾问"}) is True


def test_detect_refusal_true_on_refusal_marker() -> None:
    """即使没置 handoff 标记，出现"无法承诺"等口径也应判为拒答。"""
    payload = {"need_handoff": False, "final_reply": "我们无法承诺加急必出签。"}

    assert detect_refusal(payload) is True


def test_detect_refusal_false_for_plain_reply() -> None:
    payload = {"need_handoff": False, "final_reply": "日本旅游签证通常需要5到7个工作日。"}

    assert detect_refusal(payload) is False


def test_detect_refusal_false_for_confirm_flow() -> None:
    """confirm（中风险确认）不算拒答：系统照样给了信息，只是要求确认后继续。

    为什么必须区分：confirm 的话术里天然含"无法承诺加急/出签"这类措辞，
    如果按关键词就判成拒答，中风险场景会被误记成"系统在拒绝用户"，
    拒答精确率随之被虚假拉低，掩盖真正该关注的漏判。
    """
    payload = {
        "need_handoff": False,
        "flow_path": "confirm",
        "final_reply": "无法承诺加急时效或出签结果。请回复「确认继续」或「转人工」。",
    }

    assert detect_refusal(payload) is False


def test_detect_refusal_true_for_handoff_flow_even_without_flag() -> None:
    """flow_path=handoff 时即使 need_handoff 字段缺失，也应判为拒答。"""
    payload = {"flow_path": "handoff", "final_reply": "已为您转接高级签证顾问"}

    assert detect_refusal(payload) is True


def test_detect_cites_retrieval_false_when_no_results() -> None:
    """回复明确说明"未查询到"时，不应被记成引用了检索结果。"""
    payload = {"final_reply": "很抱歉，暂未查询到相关签证信息。"}

    assert detect_cites_retrieval(payload) is False


def test_detect_cites_retrieval_true_on_policy_detail() -> None:
    payload = {"final_reply": "日本旅游签证需提供在职证明与近6个月银行流水。"}

    assert detect_cites_retrieval(payload) is True


def test_evaluate_case_checks_cites_retrieval_expectation() -> None:
    """expect_cites_retrieval 是既有评测集在用的字段，必须被真正判定。"""
    case = {"id": "cites", "user_message": "日本签证多久？", "expect_cites_retrieval": True}

    passed_result = evaluate_case(case, _actual(final_reply="通常需要5到7个工作日。"))
    failed_result = evaluate_case(case, _actual(final_reply="很抱歉，暂未查询到相关信息。"))

    assert passed_result.passed is True
    assert failed_result.passed is False
    assert any("cites_retrieval" in failure for failure in failed_result.failures)


# ========== 单条用例判定 ==========

def _actual(**overrides) -> dict:
    """构造一份合法的最小 actual；测试只覆盖自己关心的字段。"""
    base = {
        "intent": "faq",
        "flow_path": "normal",
        "final_reply": "日本旅游签证通常需要5到7个工作日。",
        "need_handoff": False,
        "order_valid": False,
        "order_status": "",
    }
    base.update(overrides)
    return base


def test_evaluate_case_passes_when_all_expectations_met() -> None:
    case = {
        "id": "ok",
        "user_message": "日本旅游签证一般要办多久？",
        "expect_intent": "faq",
        "expect_flow_path": "normal",
        "expect_refusal": False,
    }

    result = evaluate_case(case, _actual())

    assert isinstance(result, CaseResult)
    assert result.passed is True
    assert result.failures == []


def test_evaluate_case_fails_when_intent_differs() -> None:
    case = {"id": "intent", "user_message": "x", "expect_intent": "material"}

    result = evaluate_case(case, _actual(intent="faq"))

    assert result.passed is False
    assert any("intent" in failure for failure in result.failures)


def test_evaluate_case_fails_when_flow_path_differs() -> None:
    case = {"id": "flow", "user_message": "x", "expect_flow_path": "ask"}

    result = evaluate_case(case, _actual(flow_path="normal"))

    assert result.passed is False
    assert any("flow_path" in failure for failure in result.failures)


def test_evaluate_case_fails_when_required_text_missing() -> None:
    """must_contain 是防止模型泛泛而谈的关键约束。"""
    case = {
        "id": "contain",
        "user_message": "日本旅游签材料？",
        "must_contain": ["在职证明"],
    }

    result = evaluate_case(case, _actual(final_reply="需要准备一些基本材料。"))

    assert result.passed is False
    assert any("在职证明" in failure for failure in result.failures)


def test_evaluate_case_fails_when_forbidden_text_present() -> None:
    """must_not_contain 是红线：例如不得出现"保证出签"。"""
    case = {
        "id": "forbidden",
        "user_message": "能保证过吗？",
        "must_not_contain": ["保证出签"],
    }

    result = evaluate_case(case, _actual(final_reply="我们可以保证出签。"))

    assert result.passed is False
    assert any("保证出签" in failure for failure in result.failures)


def test_evaluate_case_records_check_outcomes_for_audit() -> None:
    """报告要能逐项审计，因此每个断言都要留下期望值与实际值。"""
    case = {"id": "audit", "user_message": "x", "expect_intent": "faq"}

    result = evaluate_case(case, _actual())

    outcome = next(c for c in result.checks if c.name == "intent")
    assert isinstance(outcome, CheckOutcome)
    assert outcome.expected == "faq"
    assert outcome.actual == "faq"


def test_evaluate_case_marks_failure_when_runner_reports_error() -> None:
    """运行期异常（如 529 过载）必须算失败，而不是跳过。"""
    case = {"id": "boom", "user_message": "x", "expect_intent": "faq"}

    result = evaluate_case(case, {}, error="HTTP 529 overloaded")

    assert result.passed is False
    assert any("529" in failure for failure in result.failures)


def test_evaluate_case_fails_when_no_expectation_matched() -> None:
    """防御性检查：调用方绕过 validate_cases 时也不能判通过。"""
    case = {"id": "noop", "user_message": "x"}

    result = evaluate_case(case, _actual())

    assert result.passed is False
    assert any("期望" in failure for failure in result.failures)


# ========== 汇总指标 ==========

def _result(case_id: str, case: dict, actual: dict) -> CaseResult:
    return evaluate_case({"id": case_id, "user_message": "x", **case}, actual)


def test_aggregate_computes_intent_and_flow_accuracy() -> None:
    results = [
        _result("a", {"expect_intent": "faq"}, _actual(intent="faq")),
        _result("b", {"expect_intent": "faq"}, _actual(intent="material")),
        _result("c", {"expect_flow_path": "normal"}, _actual(flow_path="normal")),
        _result("d", {"expect_flow_path": "normal"}, _actual(flow_path="ask")),
    ]

    metrics = aggregate(results)

    assert metrics.intent_accuracy == 0.5
    assert metrics.flow_accuracy == 0.5
    assert metrics.intent_support == 2
    assert metrics.flow_support == 2


def test_aggregate_computes_refusal_precision_and_recall() -> None:
    """TP=1, FP=1, FN=1 => precision=0.5, recall=0.5。"""
    results = [
        # 期望拒答且确实拒答 -> TP
        _result(
            "tp",
            {"expect_refusal": True},
            _actual(need_handoff=True, final_reply="已转人工"),
        ),
        # 期望拒答但没拒答 -> FN
        _result(
            "fn",
            {"expect_refusal": True},
            _actual(need_handoff=False, final_reply="正常回答"),
        ),
        # 不该拒答却拒答了 -> FP
        _result(
            "fp",
            {"expect_refusal": False},
            _actual(need_handoff=True, final_reply="已转人工"),
        ),
    ]

    metrics = aggregate(results)

    assert metrics.refusal_precision == 0.5
    assert metrics.refusal_recall == 0.5
    assert metrics.refusal_true_positive == 1
    assert metrics.refusal_false_positive == 1
    assert metrics.refusal_false_negative == 1


def test_aggregate_refusal_precision_none_when_no_positive_prediction() -> None:
    """一条都没拒答时 precision 无定义，必须是 None 而不是 0.0。"""
    results = [
        _result(
            "none",
            {"expect_refusal": False},
            _actual(need_handoff=False, final_reply="正常回答"),
        )
    ]

    metrics = aggregate(results)

    assert metrics.refusal_precision is None
    assert metrics.refusal_recall is None


def test_aggregate_computes_handoff_accuracy_and_constraints() -> None:
    results = [
        _result("h1", {"expect_handoff": True}, _actual(need_handoff=True)),
        _result("h2", {"expect_handoff": False}, _actual(need_handoff=True)),
        _result("m1", {"must_contain": ["在职证明"]}, _actual(final_reply="需在职证明")),
        _result("m2", {"must_contain": ["在职证明"]}, _actual(final_reply="无")),
    ]

    metrics = aggregate(results)

    assert metrics.handoff_accuracy == 0.5
    assert metrics.handoff_support == 2
    assert metrics.constraint_pass_rate == 0.5
    assert metrics.constraint_support == 2


def test_aggregate_counts_errors_and_totals() -> None:
    results = [
        _result("ok", {"expect_intent": "faq"}, _actual()),
        evaluate_case({"id": "err", "user_message": "x", "expect_intent": "faq"}, {}, error="boom"),
    ]

    metrics = aggregate(results)

    assert metrics.total == 2
    assert metrics.failed == 1
    assert metrics.errors == 1
    assert metrics.passed == 1


def test_evaluate_case_marks_skipped_without_recording_failure() -> None:
    """需要真实模型判定、离线无法验证的用例必须显式跳过，而不是默认判通过。"""
    case = {"id": "live-only", "user_message": "火星签证怎么办？", "expect_refusal": True}

    result = evaluate_case(case, {}, skipped=True, skip_reason="需要真实模型判定")

    assert result.skipped is True
    assert result.failures == []
    assert result.passed is False


def test_aggregate_excludes_skipped_from_failed_and_counts_them() -> None:
    results = [
        _result("ok", {"expect_intent": "faq"}, _actual(intent="faq")),
        _result("bad", {"expect_intent": "material"}, _actual(intent="faq")),
        evaluate_case(
            {"id": "skip", "user_message": "x", "expect_refusal": True},
            {},
            skipped=True,
            skip_reason="需要真实模型判定",
        ),
    ]

    metrics = aggregate(results)

    assert metrics.total == 3
    assert metrics.passed == 1
    assert metrics.failed == 1  # 跳过的用例不算失败
    assert metrics.skipped == 1


# ========== 阈值门禁 ==========

def test_gate_returns_violated_metric_names() -> None:
    results = [
        _result("a", {"expect_intent": "faq"}, _actual(intent="material")),
        _result("b", {"expect_intent": "faq"}, _actual(intent="material")),
    ]
    metrics = aggregate(results)

    violations = gate(metrics, {"intent_accuracy": 0.9})

    assert len(violations) == 1
    assert "intent_accuracy" in violations[0]


def test_gate_ignores_metrics_with_none_value() -> None:
    """precision 为 None（无正类样本）时不能因为"None < 阈值"而误报失败。"""
    metrics = aggregate(
        [_result("only", {"expect_refusal": False}, _actual(final_reply="正常回答"))]
    )

    violations = gate(metrics, {"refusal_precision": 0.9})

    assert violations == []


def test_gate_passes_when_all_metrics_meet_thresholds() -> None:
    results = [_result("a", {"expect_intent": "faq"}, _actual(intent="faq"))]
    metrics = aggregate(results)

    assert gate(metrics, {"intent_accuracy": 0.9}) == []


# ========== Markdown 报告 ==========

def test_render_markdown_includes_metrics_and_failures() -> None:
    results = [
        _result("good", {"expect_intent": "faq"}, _actual(intent="faq")),
        _result("bad", {"expect_intent": "material"}, _actual(intent="faq")),
    ]
    metrics = aggregate(results)

    text = render_markdown(metrics, results, mode="offline", dataset="cases.jsonl")

    assert "intent_accuracy" in text
    assert "bad" in text
    assert "offline" in text
    assert "good" not in text.split("## 失败用例")[1] if "## 失败用例" in text else True


def test_render_markdown_states_live_mode_clearly() -> None:
    metrics = aggregate([_result("a", {"expect_intent": "faq"}, _actual())])

    text = render_markdown(metrics, [], mode="live", dataset="cases.jsonl")

    assert "live" in text
