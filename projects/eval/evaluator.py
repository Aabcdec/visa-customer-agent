"""金标评测判定器：把一次运行结果变成可解释的通过/失败与可比较的指标。

为什么需要它（而不是继续用 print 版的 run.py）：
    旧脚本每行打印 `Y` / `N`，但它既不计算指标、也不返回失败码，所以无法写进 CI，
    也无法回答"这次改动让拒答准确率涨了还是跌了"。评测要成为可依赖的门禁，必须
    满足三点：
    1. 可解释——每条失败都带上期望值与实际值，而不是只有一个 N；
    2. 可比较——汇总成固定口径的指标，历史之间能对比；
    3. 可门禁——指标低于阈值时返回具体是哪些指标挂了，供退出码使用。

正类定义（全局统一，改动需同步文档）：
    refusal 的正类是"拒答/转人工"。预测为正 = 系统确实拒答；真实为正 = 用例期望拒答。
    因此 precision 高意味着"系统不滥拒答"，recall 高意味着"该拒的都拒了"。

关于 None：
    当分母为 0（例如一条都没预测为拒答）时，precision/recall 无定义，返回 None。
    刻意不返回 0.0——0.0 会被读者理解成"表现极差"，而事实是"无法计算"。
    gate() 会跳过 None，避免因为"无法计算"而误判失败。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

# ========== 正类/口径相关常量 ==========

# "拒答"认定口径：出现这些表述说明系统在拒绝承诺或引导人工，
# 与"客服乱承诺"是互斥的两类行为，因此必须能被稳定识别。
REFUSAL_MARKERS: tuple[str, ...] = (
    "暂未查询到",
    "未查询到",
    "无法保证",
    "不能承诺",
    "无法承诺",
    "不能保证",
    "转接",
    "转人工",
    "高级签证顾问",
    "建议访问",
    "使领馆官网",
    "不支持保证出签",
    "禁止",
)

# "引用了检索/订单结果"的启发式口径：回复里出现可核对的具体政策或材料表述。
CITATION_MARKERS: tuple[str, ...] = (
    "知识库",
    "办理周期",
    "工作日",
    "有效期",
    "材料",
    "面签",
    "免签",
    "DS-160",
    "在职证明",
    "银行流水",
    "订单",
    "进度",
    "状态",
)

# 能被判定的期望字段白名单。与 dataset.ALLOWED_EXPECTATION_KEYS 保持一致。
CHECK_KEYS = frozenset(
    {
        "expect_intent",
        "expect_flow_path",
        "expect_refusal",
        "expect_handoff",
        "expect_tool_called",
        "expect_order_valid",
        "expect_cites_retrieval",
        "must_contain",
        "must_not_contain",
    }
)

# 这些字段的判定结果会进入指标统计（其余只作为单条断言）。
_INTENT_KEY = "expect_intent"
_FLOW_KEY = "expect_flow_path"
_REFUSAL_KEY = "expect_refusal"
_HANDOFF_KEY = "expect_handoff"
_TOOL_KEY = "expect_tool_called"
_ORDER_VALID_KEY = "expect_order_valid"
_CITES_KEY = "expect_cites_retrieval"

# CI 默认门槛。离线(stub)模式下 intent 不做门禁——因为离线不测模型分类能力，
# 只测"给定意图后，图是否守住了规则"，详见 offline_runner.py 的说明。
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "flow_accuracy": 0.90,
    "refusal_recall": 0.95,
    "refusal_precision": 0.80,
    "handoff_accuracy": 1.00,
    "constraint_pass_rate": 0.85,
}


# ========== 结果数据结构 ==========

@dataclass(frozen=True)
class CheckOutcome:
    """单个断言的判定结果；保留 expected/actual 以便报告可审计。"""

    name: str
    passed: bool
    expected: Any
    actual: Any
    detail: str = ""


@dataclass
class CaseResult:
    """一条用例的判定结果。

    case 原样保留：汇总指标时要回查这条用例声明了哪些期望字段，
    否则无法区分"没声明"和"声明了但通过"。

    skipped 与 passed 是两件事：跳过的用例既不算通过也不算失败。
    之所以要单独一个状态，是因为"离线环境无法验证模型判断"不等于"规则正确"，
    把它算成通过会让指标虚高。
    """

    case_id: str
    passed: bool
    checks: List[CheckOutcome] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    actual: Dict[str, Any] = field(default_factory=dict)
    case: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class Metrics:
    """汇总指标。*_support 表示该指标的样本数，用于判断指标是否可信。

    为什么带 support：3 条用例算出的 100% 和 60 条算出的 100% 完全不是一回事，
    报告里必须能看到分母。
    """

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0

    intent_accuracy: Optional[float] = None
    intent_support: int = 0

    flow_accuracy: Optional[float] = None
    flow_support: int = 0

    refusal_precision: Optional[float] = None
    refusal_recall: Optional[float] = None
    refusal_true_positive: int = 0
    refusal_false_positive: int = 0
    refusal_false_negative: int = 0

    handoff_accuracy: Optional[float] = None
    handoff_support: int = 0

    constraint_pass_rate: Optional[float] = None
    constraint_support: int = 0

    tool_success_rate: Optional[float] = None
    tool_support: int = 0


# ========== 行为识别 ==========

def detect_refusal(actual: Dict[str, Any]) -> bool:
    """判断系统这次是否在"拒答/转人工"。

    判定顺序刻意是"先结构化、后文本"：
    1. flow_path == "handoff" 或 need_handoff → 拒答（转人工即不再由机器人作答）；
    2. flow_path == "confirm" → **不是**拒答。中风险确认仍会给出信息，
       只是要求用户确认后继续；其话术里必然出现"无法承诺"，若按关键词判定
       会把中风险全判成拒答，让拒答精确率失真；
    3. 以上都没有结构化信息时（例如线上接口未返回 flow_path），
       才退回关键词判断。

    两个来源取"或"而不是"且"：避免把"已转人工但回复很短"漏判。
    """
    flow_path = str(actual.get("flow_path") or "")
    if flow_path == "handoff" or actual.get("need_handoff"):
        return True
    if flow_path == "confirm":
        return False

    reply = str(actual.get("final_reply") or "")
    return any(marker in reply for marker in REFUSAL_MARKERS)


def detect_cites_retrieval(actual: Dict[str, Any]) -> bool:
    """判断回复是否引用了检索/订单这类可核对的结果。

    "未查询到"类回复虽然也提到"查询"，但本质是没有引用到任何内容，必须排除，
    否则"什么都不知道但语气像查过"会被误判成高质量回答。
    """
    reply = str(actual.get("final_reply") or "")
    if not reply:
        return False
    if "暂未查询到" in reply or "未查询到" in reply:
        return False
    return any(marker in reply for marker in CITATION_MARKERS)


# ========== 单条用例判定 ==========

def evaluate_case(
    case: Dict[str, Any],
    actual: Dict[str, Any],
    error: str = "",
    skipped: bool = False,
    skip_reason: str = "",
) -> CaseResult:
    """按用例声明的期望逐项判定。

    参数:
        case:        评测集中的一条用例
        actual:      实际运行结果（/run 的返回或离线运行的结果）
        error:       运行期错误信息；非空时直接判失败，不进入字段比对
        skipped:     是否需要跳过判定（例如离线环境无法验证模型判断）
        skip_reason: 跳过原因，会写进报告，避免"跳过"变成黑盒
    """
    case_id = str(case.get("id", "?"))

    if skipped:
        # 刻意不走断言流程：跳过就是跳过，不能顺带把断言判成"通过"。
        return CaseResult(
            case_id=case_id,
            passed=False,
            checks=[],
            failures=[],
            actual=actual,
            case=case,
            skipped=True,
            skip_reason=skip_reason or "未说明跳过原因",
        )

    checks: List[CheckOutcome] = []
    failures: List[str] = []

    if error:
        failures.append(f"运行失败: {error}")
        return CaseResult(
            case_id=case_id,
            passed=False,
            checks=checks,
            failures=failures,
            actual=actual,
            case=case,
            error=error,
        )

    matched_expectation = False

    if _INTENT_KEY in case:
        matched_expectation = True
        expected = case[_INTENT_KEY]
        got = actual.get("intent")
        ok = got == expected
        checks.append(CheckOutcome("intent", ok, expected, got))
        if not ok:
            failures.append(f"intent 期望={expected!r} 实际={got!r}")

    if _FLOW_KEY in case:
        matched_expectation = True
        expected = case[_FLOW_KEY]
        got = actual.get("flow_path")
        ok = got == expected
        checks.append(CheckOutcome("flow_path", ok, expected, got))
        if not ok:
            failures.append(f"flow_path 期望={expected!r} 实际={got!r}")

    if _REFUSAL_KEY in case:
        matched_expectation = True
        expected = bool(case[_REFUSAL_KEY])
        got = detect_refusal(actual)
        ok = got == expected
        checks.append(CheckOutcome("refusal", ok, expected, got))
        if not ok:
            failures.append(f"refusal 期望={expected} 实际={got}")

    if _HANDOFF_KEY in case:
        matched_expectation = True
        expected = bool(case[_HANDOFF_KEY])
        got = bool(actual.get("need_handoff"))
        ok = got == expected
        checks.append(CheckOutcome("handoff", ok, expected, got))
        if not ok:
            failures.append(f"handoff 期望={expected} 实际={got}")

    if _TOOL_KEY in case:
        matched_expectation = True
        expected = bool(case[_TOOL_KEY])
        got = bool(actual.get("order_status"))
        ok = got == expected
        checks.append(CheckOutcome("tool_called", ok, expected, got))
        if not ok:
            failures.append(f"tool_called 期望={expected} 实际={got}")

    if _ORDER_VALID_KEY in case:
        matched_expectation = True
        expected = bool(case[_ORDER_VALID_KEY])
        got = bool(actual.get("order_valid"))
        ok = got == expected
        checks.append(CheckOutcome("order_valid", ok, expected, got))
        if not ok:
            failures.append(f"order_valid 期望={expected} 实际={got}")

    if _CITES_KEY in case:
        matched_expectation = True
        expected = bool(case[_CITES_KEY])
        got = detect_cites_retrieval(actual)
        ok = got == expected
        checks.append(CheckOutcome("cites_retrieval", ok, expected, got))
        if not ok:
            failures.append(f"cites_retrieval 期望={expected} 实际={got}")

    reply = str(actual.get("final_reply") or "")

    if "must_contain" in case:
        matched_expectation = True
        required = list(case["must_contain"])
        missing = [text for text in required if text not in reply]
        ok = not missing
        checks.append(CheckOutcome("must_contain", ok, required, reply[:200]))
        if not ok:
            failures.append(f"must_contain 缺少文本: {missing}")

    if "must_not_contain" in case:
        matched_expectation = True
        forbidden = list(case["must_not_contain"])
        hit = [text for text in forbidden if text in reply]
        ok = not hit
        checks.append(CheckOutcome("must_not_contain", ok, forbidden, reply[:200]))
        if not ok:
            failures.append(f"must_not_contain 出现禁止文本: {hit}")

    if not matched_expectation:
        # 防御性兜底：调用方绕过 dataset.validate_cases 时，绝不能因为
        # "没有任何断言"就判通过。
        failures.append("用例没有任何可判定的期望字段，无法判定（疑似字段拼写错误）")

    return CaseResult(
        case_id=case_id,
        passed=not failures,
        checks=checks,
        failures=failures,
        actual=actual,
        case=case,
    )


# ========== 汇总 ==========

def _rate(numerator: int, denominator: int) -> Optional[float]:
    """安全比率：分母为 0 时返回 None（无定义），而不是 0.0。"""
    if denominator <= 0:
        return None
    return numerator / denominator


def aggregate(results: Sequence[CaseResult]) -> Metrics:
    """把逐条结果汇总为指标。

    跳过的用例不参与任何指标计算：它们的 actual 是空的，如果混进来会把
    准确率算成 0，得出"系统全错"的错误结论。
    """
    metrics = Metrics(total=len(results))
    metrics.passed = sum(1 for r in results if r.passed)
    metrics.skipped = sum(1 for r in results if r.skipped)
    metrics.errors = sum(1 for r in results if r.error and not r.skipped)
    # 跳过既不算通过也不算失败，必须从 failed 里剔除。
    metrics.failed = metrics.total - metrics.passed - metrics.skipped

    intent_ok = intent_seen = 0
    flow_ok = flow_seen = 0
    handoff_ok = handoff_seen = 0
    constraint_ok = constraint_seen = 0
    tool_ok = tool_seen = 0
    tp = fp = fn = 0

    for result in results:
        if result.skipped:
            continue
        case = result.case or {}
        actual = result.actual or {}

        if _INTENT_KEY in case:
            intent_seen += 1
            if actual.get("intent") == case[_INTENT_KEY]:
                intent_ok += 1

        if _FLOW_KEY in case:
            flow_seen += 1
            if actual.get("flow_path") == case[_FLOW_KEY]:
                flow_ok += 1

        if _HANDOFF_KEY in case:
            handoff_seen += 1
            if bool(actual.get("need_handoff")) == bool(case[_HANDOFF_KEY]):
                handoff_ok += 1

        if _TOOL_KEY in case:
            tool_seen += 1
            if bool(actual.get("order_status")) == bool(case[_TOOL_KEY]):
                tool_ok += 1

        if "must_contain" in case or "must_not_contain" in case:
            constraint_seen += 1
            if all(c.passed for c in result.checks if c.name in ("must_contain", "must_not_contain")):
                constraint_ok += 1

        if _REFUSAL_KEY in case:
            truth = bool(case[_REFUSAL_KEY])
            predicted = detect_refusal(actual)
            if truth and predicted:
                tp += 1
            elif not truth and predicted:
                fp += 1
            elif truth and not predicted:
                fn += 1

    metrics.intent_accuracy = _rate(intent_ok, intent_seen)
    metrics.intent_support = intent_seen
    metrics.flow_accuracy = _rate(flow_ok, flow_seen)
    metrics.flow_support = flow_seen
    metrics.handoff_accuracy = _rate(handoff_ok, handoff_seen)
    metrics.handoff_support = handoff_seen
    metrics.constraint_pass_rate = _rate(constraint_ok, constraint_seen)
    metrics.constraint_support = constraint_seen
    metrics.tool_success_rate = _rate(tool_ok, tool_seen)
    metrics.tool_support = tool_seen

    metrics.refusal_true_positive = tp
    metrics.refusal_false_positive = fp
    metrics.refusal_false_negative = fn
    metrics.refusal_precision = _rate(tp, tp + fp)
    metrics.refusal_recall = _rate(tp, tp + fn)

    return metrics


# ========== 阈值门禁 ==========

def gate(metrics: Metrics, thresholds: Dict[str, float]) -> List[str]:
    """返回未达标的指标说明列表；空列表表示全部达标。

    跳过 None：指标无法计算时不应被当成"低于阈值"，否则会制造假警报。
    """
    violations: List[str] = []
    for name, minimum in thresholds.items():
        value = getattr(metrics, name, None)
        if value is None:
            continue
        if value < minimum:
            violations.append(f"{name}: {value:.4f} < 阈值 {minimum:.4f}")
    return violations


# ========== 报告 ==========

def _fmt(value: Optional[float]) -> str:
    """比率格式化：None 显示为 n/a，避免读者把"无法计算"误读为 0。"""
    return "n/a" if value is None else f"{value:.4f}"


def render_markdown(
    metrics: Metrics,
    results: Sequence[CaseResult],
    mode: str,
    dataset: str,
) -> str:
    """渲染 Markdown 报告。

    结构上把"失败用例"放在最后一节，这样读者（和测试）可以确认：
    失败清单里只出现真正失败的用例。
    """
    lines: List[str] = []
    lines.append("# 签证客服 Agent 评测报告")
    lines.append("")
    lines.append(f"- 运行模式: **{mode}**")
    lines.append(f"- 评测集: `{dataset}`")
    lines.append(f"- 用例总数: {metrics.total}（通过 {metrics.passed} / 失败 {metrics.failed}）")
    lines.append(f"- 运行期错误: {metrics.errors}")
    lines.append(f"- 跳过(离线无法验证): {metrics.skipped}")
    lines.append("")

    lines.append("## 总体指标")
    lines.append("")
    lines.append("| 指标 | 值 | 样本数 | 说明 |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| intent_accuracy | {_fmt(metrics.intent_accuracy)} | {metrics.intent_support} "
        "| 意图分类准确率 |"
    )
    lines.append(
        f"| flow_accuracy | {_fmt(metrics.flow_accuracy)} | {metrics.flow_support} "
        "| 流程路径(ask/confirm/normal/handoff/chitchat)准确率 |"
    )
    lines.append(
        f"| refusal_precision | {_fmt(metrics.refusal_precision)} | "
        f"{metrics.refusal_true_positive + metrics.refusal_false_positive} "
        "| 拒答精确率（高=不滥拒答） |"
    )
    lines.append(
        f"| refusal_recall | {_fmt(metrics.refusal_recall)} | "
        f"{metrics.refusal_true_positive + metrics.refusal_false_negative} "
        "| 拒答召回率（高=该拒的都拒了） |"
    )
    lines.append(
        f"| handoff_accuracy | {_fmt(metrics.handoff_accuracy)} | {metrics.handoff_support} "
        "| 转人工判定准确率 |"
    )
    lines.append(
        f"| constraint_pass_rate | {_fmt(metrics.constraint_pass_rate)} | "
        f"{metrics.constraint_support} | 文本约束(must_contain/must_not_contain)通过率 |"
    )
    lines.append(
        f"| tool_success_rate | {_fmt(metrics.tool_success_rate)} | {metrics.tool_support} "
        "| 订单查询是否返回了状态 |"
    )
    lines.append("")
    lines.append(
        f"> 混淆矩阵：TP={metrics.refusal_true_positive} "
        f"FP={metrics.refusal_false_positive} FN={metrics.refusal_false_negative}"
    )
    lines.append("")
    if mode != "live":
        lines.append(
            "> 注意：本次为**离线（stub LLM）**运行。意图由夹具注入，"
            "因此 intent_accuracy 不代表真实模型能力；"
            "它验证的是「给定意图后，图的风控与路由是否守住规则」。"
            "需要评估真实模型请使用 live 模式。"
        )
        lines.append("")

    failed = [r for r in results if not r.passed and not r.skipped]
    lines.append("## 失败用例")
    lines.append("")
    if not failed:
        lines.append("无。")
        lines.append("")
    for result in failed:
        lines.append(f"### {result.case_id}")
        lines.append("")
        lines.append(f"- 用户消息: {result.case.get('user_message', '')}")
        for failure in result.failures:
            lines.append(f"- 失败: {failure}")
        lines.append("")
        reply = str(result.actual.get("final_reply") or "").replace("\n", " ")
        if reply:
            lines.append(f"- 实际回复(截断): {reply[:200]}")
            lines.append("")

    skipped = [r for r in results if r.skipped]
    if skipped:
        lines.append("## 跳过的用例")
        lines.append("")
        lines.append("这些用例需要真实模型判断，离线(stub)模式下无法验证，因此不计入指标。")
        lines.append("")
        for result in skipped:
            lines.append(f"- `{result.case_id}`：{result.skip_reason}")

    return "\n".join(lines)
