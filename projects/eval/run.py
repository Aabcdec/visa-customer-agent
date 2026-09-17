"""金标评测 CLI：跑评测集 → 出指标 → 写报告 → 用退出码做门禁。

用法：
    # 离线模式（推荐日常/CI 使用，不需要 API Key、不花钱）
    python eval/run.py --mode offline

    # 线上模式（需要先起服务：bash scripts/http_run.sh -p 5000）
    python eval/run.py --mode live --base-url http://127.0.0.1:5000

    # 冒烟：只跑前 10 条
    python eval/run.py --mode offline --limit 10

    # 只改某几个阈值（例如本地调试时放宽）
    python eval/run.py --mode offline --threshold flow_accuracy=0.8

产物：
    eval/reports/report.json   机器可读（含逐条结果与指标），便于趋势对比
    eval/reports/report.md     人可读，失败原因与跳过原因都在里面

退出码：
    0  全部通过且指标达标
    1  环境/配置错误（评测集非法、服务不可达）
    2  有用例失败，或指标未达阈值

为什么退出码要区分 1 和 2：
    "评测集写错了" 和 "系统行为不对" 是两类完全不同的故障，
    CI 里需要能一眼分辨，否则会把数据集笔误误当成模型退化。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 兼容 `python eval/run.py` 与 `python -m eval.run` 两种调用方式：
# 直接执行时 sys.path[0] 是 eval/ 目录，拿不到 eval 包本身和 src/。
if __package__ in (None, ""):
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "src")):
        if _path not in sys.path:
            sys.path.insert(0, _path)

from eval.dataset import load_cases  # noqa: E402
from eval.evaluator import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    CaseResult,
    aggregate,
    evaluate_case,
    gate,
    render_markdown,
)
from eval.offline_runner import offline_case_view, run_case_offline  # noqa: E402

DEFAULT_CASES = Path(__file__).resolve().parent / "cases.jsonl"
DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"

# 离线模式不评意图（expect_intent 是注入输入，详见 offline_case_view），
# 因此这两个指标在离线报告里必然为 n/a，不参与门禁。
LIVE_ONLY_THRESHOLDS = frozenset({"intent_accuracy"})


def _parse_thresholds(raw: List[str]) -> Dict[str, float]:
    """解析 --threshold name=value。写错名字要立刻报错，否则会以为门禁生效了。"""
    parsed = dict(DEFAULT_THRESHOLDS)
    for item in raw:
        if "=" not in item:
            raise ValueError(f"--threshold 需要 name=value 形式，收到: {item}")
        name, _, value = item.partition("=")
        name = name.strip()
        if name not in DEFAULT_THRESHOLDS:
            raise ValueError(
                f"未知阈值 {name!r}；可用: {sorted(DEFAULT_THRESHOLDS)}"
            )
        parsed[name] = float(value)
    return parsed


def _call_run(base_url: str, user_message: str, timeout: float) -> Dict[str, Any]:
    """调用线上 /run 端点。"""
    url = base_url.rstrip("/") + "/run"
    body = json.dumps({"user_message": user_message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _run_offline_cases(cases: List[Dict[str, Any]]) -> List[CaseResult]:
    """离线跑全部用例。

    标记 requires_llm 的用例直接跳过：它们的结论依赖模型判断，
    用桩去"判通过"是自欺欺人。
    """
    results: List[CaseResult] = []
    for case in cases:
        if case.get("requires_llm"):
            results.append(
                evaluate_case(
                    case,
                    {},
                    skipped=True,
                    skip_reason="结论依赖模型判断，离线(stub)模式无法验证",
                )
            )
            continue

        actual = run_case_offline(case)
        # 用 offline_case_view 去掉 expect_intent，避免自证式 100% 准确率。
        results.append(evaluate_case(offline_case_view(case), actual))
    return results


def _run_live_cases(
    cases: List[Dict[str, Any]],
    base_url: str,
    timeout: float,
) -> Tuple[List[CaseResult], Optional[str]]:
    """对着真实服务跑全部用例；返回 (结果, 致命错误)。"""
    results: List[CaseResult] = []
    for case in cases:
        try:
            actual = _call_run(base_url, case["user_message"], timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            results.append(
                evaluate_case(case, {}, error=f"HTTP {exc.code}: {body}")
            )
        except Exception as exc:  # noqa: BLE001 — 单条失败不应中断整轮评测
            results.append(evaluate_case(case, {}, error=str(exc)))
        else:
            results.append(evaluate_case(case, actual))
    return results, None


def _summarize(results: List[CaseResult]) -> str:
    """终端摘要：先给结论，再给失败清单，避免只打印一堆 Y/N。"""
    lines: List[str] = []
    passed = sum(1 for r in results if r.passed)
    skipped = sum(1 for r in results if r.skipped)
    failed = [r for r in results if not r.passed and not r.skipped]

    lines.append("")
    lines.append(f"用例: {len(results)}  通过: {passed}  失败: {len(failed)}  跳过: {skipped}")
    if failed:
        lines.append("")
        lines.append("失败明细:")
        for result in failed:
            lines.append(f"  ✗ {result.case_id}")
            for failure in result.failures:
                lines.append(f"      {failure}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="签证客服 Agent 金标评测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="offline=进程内 stub LLM（默认，CI 用）；live=调用真实服务",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="live 模式的服务地址")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条（冒烟用）")
    parser.add_argument("--timeout", type=float, default=120.0, help="live 模式单条超时秒数")
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=f"覆盖门禁阈值，可重复；可用: {sorted(DEFAULT_THRESHOLDS)}",
    )
    parser.add_argument("--no-gate", action="store_true", help="只出报告，不因阈值失败")
    args = parser.parse_args()

    try:
        thresholds = _parse_thresholds(args.threshold)
    except ValueError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 1

    try:
        cases = load_cases(args.cases, limit=args.limit)
    except Exception as exc:  # noqa: BLE001 — 评测集非法属于配置错误
        print(f"评测集加载失败: {exc}", file=sys.stderr)
        return 1

    if not cases:
        print(f"评测集为空: {args.cases}", file=sys.stderr)
        return 1

    print(f"模式: {args.mode}  评测集: {args.cases}  用例数: {len(cases)}")

    if args.mode == "offline":
        results = _run_offline_cases(cases)
        effective_thresholds = {
            name: value
            for name, value in thresholds.items()
            if name not in LIVE_ONLY_THRESHOLDS
        }
    else:
        results, fatal = _run_live_cases(cases, args.base_url, args.timeout)
        if fatal:
            print(f"线上模式致命错误: {fatal}", file=sys.stderr)
            return 1
        effective_thresholds = thresholds

    metrics = aggregate(results)
    violations = gate(metrics, effective_thresholds)

    print(_summarize(results))
    print("")
    print("指标:")
    for name, value in (
        ("intent_accuracy", metrics.intent_accuracy),
        ("flow_accuracy", metrics.flow_accuracy),
        ("refusal_precision", metrics.refusal_precision),
        ("refusal_recall", metrics.refusal_recall),
        ("handoff_accuracy", metrics.handoff_accuracy),
        ("constraint_pass_rate", metrics.constraint_pass_rate),
    ):
        shown = "n/a" if value is None else f"{value:.4f}"
        print(f"  {name:<22} {shown}")

    if violations:
        print("")
        print("未达阈值:")
        for violation in violations:
            print(f"  ! {violation}")

    # 写报告（即使失败也要写，失败现场最有价值）
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / "report.json"
    md_path = args.report_dir / "report.md"

    payload = {
        "mode": args.mode,
        "dataset": str(args.cases),
        "thresholds": effective_thresholds,
        "metrics": metrics.__dict__,
        "violations": violations,
        "cases": [
            {
                "id": r.case_id,
                "passed": r.passed,
                "skipped": r.skipped,
                "skip_reason": r.skip_reason,
                "error": r.error,
                "failures": r.failures,
                "actual": r.actual,
            }
            for r in results
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        render_markdown(metrics, results, mode=args.mode, dataset=str(args.cases)),
        encoding="utf-8",
    )

    print("")
    print(f"报告: {json_path} / {md_path}")

    if metrics.failed and not args.no_gate:
        return 2
    if violations and not args.no_gate:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
