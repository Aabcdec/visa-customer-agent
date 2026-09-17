"""金标评测集读取与校验。

为什么单独成模块：
    评测集是本项目最重要的"资产"之一，但 JSONL 一旦字段拼错（例如把
    expect_flow_path 写成 expected_flow_path），旧脚本只会静静地不做任何检查、
    仍然打印"通过"。这会让一套本该发现问题的评测集变成装饰品。

    因此这里采用"白名单 + 显式报错"策略：
    - 只接受已知字段，未知字段直接抛错（拼错立刻暴露）；
    - 重复 id、空 user_message、非法布尔值一律拒绝；
    - 校验在加载阶段完成，而不是等到跑完 60 条才发现某条没被检查。

用法：
    from eval.dataset import load_cases, validate_cases
    cases = load_cases(Path("eval/cases.jsonl"))
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

# 合法的"期望字段"白名单。新增指标时必须同步更新这里和 evaluator.CHECK_KEYS，
# 否则写错的字段会被当成未知字段拦下来。
ALLOWED_EXPECTATION_KEYS = frozenset(
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

# 非期望字段：用于描述用例本身，不参与判定。
# requires_llm 标记"这条用例的结论依赖模型判断"，离线(stub)模式下必须跳过——
# 否则离线 harness 会通过"把答案喂给 stub"的方式自欺欺人地判通过。
ALLOWED_METADATA_KEYS = frozenset({"id", "user_message", "tags", "note", "requires_llm"})

ALLOWED_KEYS = ALLOWED_EXPECTATION_KEYS | ALLOWED_METADATA_KEYS

_BOOL_KEYS = frozenset(
    {
        "expect_refusal",
        "expect_handoff",
        "expect_tool_called",
        "expect_order_valid",
        "expect_cites_retrieval",
        "requires_llm",
    }
)
_LIST_KEYS = frozenset({"must_contain", "must_not_contain", "tags"})


class DatasetError(ValueError):
    """评测集结构非法。继承 ValueError，方便调用方统一 except。"""


def load_cases(path: Path, limit: int | None = None) -> List[Dict[str, Any]]:
    """读取 JSONL 评测集并逐条校验，返回用例列表。

    参数:
        path: cases.jsonl 路径
        limit: 只取前 N 条（便于本地快速冒烟）
    """
    if not path.exists():
        raise DatasetError(f"评测集文件不存在: {path}")

    cases: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{path}:{line_no} JSON 解析失败: {exc}") from exc
            if not isinstance(case, dict):
                raise DatasetError(f"{path}:{line_no} 每条用例必须是 JSON 对象")
            cases.append(case)
            if limit is not None and len(cases) >= limit:
                break

    validate_cases(cases, source=str(path))
    return cases


def validate_cases(cases: Iterable[Dict[str, Any]], source: str = "<memory>") -> None:
    """校验用例集合；任何结构问题都抛 DatasetError，绝不静默放过。"""
    seen_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        where = f"{source} 第{index}条"

        case_id = case.get("id")
        if not case_id or not isinstance(case_id, str):
            raise DatasetError(f"{where}: 缺少非空字符串字段 id")
        if case_id in seen_ids:
            raise DatasetError(f"{where}: 用例 id 重复 -> {case_id}")
        seen_ids.add(case_id)

        message = case.get("user_message")
        if not message or not isinstance(message, str) or not message.strip():
            raise DatasetError(f"{where}({case_id}): user_message 必须是非空字符串")

        unknown = set(case) - ALLOWED_KEYS
        if unknown:
            raise DatasetError(
                f"{where}({case_id}): 存在未知字段 {sorted(unknown)}；"
                f"合法字段为 {sorted(ALLOWED_KEYS)}"
            )

        # 至少要有 1 个期望字段，否则这条用例永远不会被检查（假通过）。
        if not (set(case) & ALLOWED_EXPECTATION_KEYS):
            raise DatasetError(
                f"{where}({case_id}): 至少需要 1 个期望字段，"
                f"可从 {sorted(ALLOWED_EXPECTATION_KEYS)} 中选择"
            )

        for key in _BOOL_KEYS & set(case):
            if not isinstance(case[key], bool):
                raise DatasetError(f"{where}({case_id}): {key} 必须是布尔值")

        for key in _LIST_KEYS & set(case):
            value = case[key]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise DatasetError(f"{where}({case_id}): {key} 必须是字符串数组")

        for key in ("expect_intent", "expect_flow_path"):
            if key in case and not isinstance(case[key], str):
                raise DatasetError(f"{where}({case_id}): {key} 必须是字符串")
