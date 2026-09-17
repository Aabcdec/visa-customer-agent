"""评测集读取与校验的测试（先写测试，再写实现）。

这些测试保护的是"评测集本身不能悄悄失效"：
    - 字段拼错必须报错，而不是被静默忽略；
    - 重复 id 必须报错，否则报告里两条用例互相覆盖；
    - 一条用例至少要有一个期望字段，否则它永远不会失败（假通过）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.dataset import (
    ALLOWED_EXPECTATION_KEYS,
    DatasetError,
    load_cases,
    validate_cases,
)


def _write_jsonl(tmp_path: Path, cases: list[dict]) -> Path:
    """把用例写成临时 JSONL，返回路径。"""
    path = tmp_path / "cases.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    return path


def test_load_cases_reads_valid_jsonl(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        [
            {"id": "c1", "user_message": "日本签证要多久？", "expect_intent": "faq"},
            {"id": "c2", "user_message": "你好", "expect_intent": "chitchat"},
        ],
    )

    cases = load_cases(path)

    assert [case["id"] for case in cases] == ["c1", "c2"]


def test_load_cases_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '\n{"id": "c1", "user_message": "你好", "expect_intent": "chitchat"}\n\n',
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert len(cases) == 1


def test_load_cases_respects_limit(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path,
        [
            {"id": f"c{i}", "user_message": f"消息{i}", "expect_intent": "faq"}
            for i in range(5)
        ],
    )

    cases = load_cases(path, limit=2)

    assert len(cases) == 2


def test_load_cases_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="不存在"):
        load_cases(tmp_path / "nope.jsonl")


def test_load_cases_raises_on_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="JSON 解析失败"):
        load_cases(path)


def test_validate_rejects_unknown_expectation_key() -> None:
    """把 expect_flow_path 拼成 expected_flow_path 必须立刻失败。"""
    cases = [
        {
            "id": "typo",
            "user_message": "日本签证要多久？",
            "expected_flow_path": "normal",
        }
    ]

    with pytest.raises(DatasetError, match="未知字段"):
        validate_cases(cases)


def test_validate_rejects_duplicate_ids() -> None:
    cases = [
        {"id": "dup", "user_message": "第一个", "expect_intent": "faq"},
        {"id": "dup", "user_message": "第二个", "expect_intent": "faq"},
    ]

    with pytest.raises(DatasetError, match="重复"):
        validate_cases(cases)


def test_validate_rejects_case_without_expectation() -> None:
    """没有任何期望字段的用例永远不会失败，属于假通过，必须拒绝。"""
    cases = [{"id": "noop", "user_message": "随便一句"}]

    with pytest.raises(DatasetError, match="期望字段"):
        validate_cases(cases)


def test_validate_rejects_empty_user_message() -> None:
    cases = [{"id": "empty", "user_message": "   ", "expect_intent": "faq"}]

    with pytest.raises(DatasetError, match="user_message"):
        validate_cases(cases)


def test_validate_accepts_cites_retrieval_flag() -> None:
    """expect_cites_retrieval 是既有评测集使用的字段，必须被白名单接受。"""
    cases = [
        {
            "id": "cites",
            "user_message": "日本旅游签证一般要办多久？",
            "expect_cites_retrieval": True,
        }
    ]

    validate_cases(cases)


def test_validate_rejects_non_boolean_flag() -> None:
    """expect_refusal 写成字符串 "true" 是常见笔误，必须拒绝。"""
    cases = [
        {
            "id": "bad-bool",
            "user_message": "火星签证怎么办？",
            "expect_refusal": "true",
        }
    ]

    with pytest.raises(DatasetError, match="布尔值"):
        validate_cases(cases)


def test_validate_rejects_non_list_must_contain() -> None:
    cases = [
        {
            "id": "bad-list",
            "user_message": "日本签证要多久？",
            "must_contain": "材料",
        }
    ]

    with pytest.raises(DatasetError, match="字符串数组"):
        validate_cases(cases)


def test_shipped_cases_file_is_valid() -> None:
    """真实评测集必须始终能通过校验——这是数据集改坏时的第一道防线。"""
    cases_path = Path(__file__).resolve().parents[1] / "eval" / "cases.jsonl"

    cases = load_cases(cases_path)

    assert len(cases) >= 1
    # 每条用例至少要检查 intent 或 flow_path 之一，避免退化成无意义用例。
    for case in cases:
        assert set(case) & ALLOWED_EXPECTATION_KEYS
