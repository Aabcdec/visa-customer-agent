"""跑一遍 /run：打印是否拒答、是否引用检索。

用法:
  # 先启动服务: bash scripts/http_run.sh -p 5000
  python eval/run.py
  python eval/run.py --base-url http://127.0.0.1:5000 --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CASES_PATH = Path(__file__).resolve().parent / "cases.jsonl"

# 拒答/转人工：无知识、禁承诺、高风险 handoff
REFUSAL_MARKERS = (
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

# 回复里出现可核对的政策/材料表述，视为引用了检索或订单结果
CITATION_MARKERS = (
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


def load_cases(path: Path, limit: int | None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
            if limit is not None and len(cases) >= limit:
                break
    return cases


def call_run(base_url: str, user_message: str, timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/run"
    body = json.dumps({"user_message": user_message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def detect_refusal(result: dict[str, Any]) -> bool:
    if result.get("need_handoff"):
        return True
    reply = str(result.get("final_reply") or "")
    return any(marker in reply for marker in REFUSAL_MARKERS)


def detect_cites_retrieval(result: dict[str, Any]) -> bool:
    # GraphOutput 不含 knowledge_context，用回复文本启发式判断是否像引用检索/插件结果
    reply = str(result.get("final_reply") or "")
    if not reply:
        return False
    if "暂未查询到" in reply or "未查询到" in reply:
        return False
    return any(marker in reply for marker in CITATION_MARKERS)


def mark(ok: bool | None) -> str:
    if ok is None:
        return "-"
    return "Y" if ok else "N"


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval harness for visa-customer /run")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    cases = load_cases(args.cases, args.limit)
    if not cases:
        print(f"No cases in {args.cases}", file=sys.stderr)
        return 1

    print(
        f"{'id':<28} {'intent':<10} {'拒答':^6} {'引用检索':^8} "
        f"{'期望拒答':^8} {'期望引用':^8} {'HTTP':^6}"
    )
    print("-" * 90)

    errors = 0
    for case in cases:
        case_id = case.get("id", "?")
        try:
            result = call_run(args.base_url, case["user_message"], args.timeout)
            status = "ok"
        except urllib.error.HTTPError as exc:
            errors += 1
            body = exc.read().decode("utf-8", errors="replace")[:200]
            print(f"{case_id:<28} {'ERR':<10} {'-':^6} {'-':^8} {'-':^8} {'-':^8} {exc.code:^6} {body}")
            continue
        except Exception as exc:  # noqa: BLE001 — eval 脚本要吞掉并继续下一条
            errors += 1
            print(f"{case_id:<28} {'ERR':<10} {'-':^6} {'-':^8} {'-':^8} {'-':^8} {'fail':^6} {exc}")
            continue

        is_refusal = detect_refusal(result)
        cites = detect_cites_retrieval(result)
        intent = str(result.get("intent") or "")[:10]
        print(
            f"{case_id:<28} {intent:<10} "
            f"{mark(is_refusal):^6} {mark(cites):^8} "
            f"{mark(case.get('expect_refusal')):^8} "
            f"{mark(case.get('expect_cites_retrieval')):^8} "
            f"{status:^6}"
        )
        reply = str(result.get("final_reply") or "").replace("\n", " ")
        if reply:
            print(f"  reply: {reply[:160]}{'...' if len(reply) > 160 else ''}")

    print("-" * 90)
    print(f"done: {len(cases)} cases, errors={errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
