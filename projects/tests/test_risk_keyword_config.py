"""风险关键词配置一致性测试。

为什么单独测"配置"而不是只测"行为"：
    风控的匹配逻辑是"先扫高风险，命中就转人工；否则再扫中风险"。
    在这个模式下，只要两个列表之间存在**同词**或**子串包含**关系，
    较短/较高优先级的那条就会遮蔽另一条 —— 被遮蔽的规则是**死代码**，
    但它看起来在工作（行为上确实触发了转人工，只是理由错了）。

    真实案例：「拒签」曾在高风险列表，「之前拒签」在中风险列表。
    后者永远不可能被单独命中，因为前者必然同时命中。

    行为测试很难覆盖这类问题：你得恰好想到那个被遮蔽的说法才会发现。
    配置测试则是集合级别的，一次就能扫出全部冲突。

这几个断言很便宜（几十行），但能挡住一整类人为错误。
"""
from __future__ import annotations

import pytest

from graphs.nodes.risk_assessment_node import (
    HIGH_RISK_KEYWORDS,
    MEDIUM_RISK_KEYWORDS,
)


def test_no_keyword_appears_in_both_tiers() -> None:
    """同一条关键词不允许同时出现在两个等级里。

    出现即意味着其中一条永远不生效，且"它到底算哪档"变得不可判断。
    """
    overlap = set(HIGH_RISK_KEYWORDS) & set(MEDIUM_RISK_KEYWORDS)

    assert not overlap, f"高/中风险关键词存在重叠，至少一条永不生效: {sorted(overlap)}"


def test_no_substring_shadowing_between_tiers() -> None:
    """跨等级不允许存在子串包含关系。

    若高风险里有 A、中风险里有 B 且 A 是 B 的子串（或反之），
    那么 B 命中时 A 必然同时命中，而高风险先判 —— B 被静默遮蔽。

    这正是「拒签 / 之前拒签」那个 bug 的形态。
    """
    conflicts = [
        (high, medium)
        for high in HIGH_RISK_KEYWORDS
        for medium in MEDIUM_RISK_KEYWORDS
        if high in medium or medium in high
    ]

    assert not conflicts, (
        "存在跨等级子串包含关系，较短者会遮蔽较长者: "
        f"{conflicts}。请只保留更宽泛的那条裸关键词。"
    )


def test_keywords_are_not_empty() -> None:
    assert HIGH_RISK_KEYWORDS
    assert MEDIUM_RISK_KEYWORDS
    assert all(kw.strip() for kw in HIGH_RISK_KEYWORDS)
    assert all(kw.strip() for kw in MEDIUM_RISK_KEYWORDS)


def test_violation_keywords_stay_high_risk() -> None:
    """真实违规/失信类关键词必须留在高风险——防止"放松判断"改过头。"""
    for keyword in ["遣返", "非法滞留", "造假", "伪造", "黑名单", "包过"]:
        assert keyword in HIGH_RISK_KEYWORDS, f"{keyword} 属于违规/失信类，必须保留在高风险"


def test_rejection_keyword_stays_medium_risk() -> None:
    """被拒签是合法的再申请场景，必须留在中风险。"""
    assert "拒签" in MEDIUM_RISK_KEYWORDS
    assert "拒签" not in HIGH_RISK_KEYWORDS
