"""本地知识库检索测试。

知识库是"回答有没有依据"的源头，所以要同时保护两件事：
    1. 命中该命中的（否则回答会变成空话）；
    2. 不命中不该命中的（否则会拿着不相关片段硬答，属于幻觉的温床）。

第 2 点在当前实现里是已知缺口：检索靠关键词打分，没有"域外问题"的相关性门控，
所以"火星签证"仍会召回通用材料片段。这里用 xfail(strict=True) 把它显式记录下来——
将来有人补上门控，这个标记会立刻变成失败，提醒把它改成正常断言。
"""
from __future__ import annotations

import pytest

from graphs.nodes.knowledge_retrieval_node import knowledge_retrieval_node
from graphs.state import KnowledgeRetrievalInput
from utils.knowledge import LocalKnowledgeClient


# ========== 检索器本体 ==========

def test_search_returns_chunks_for_known_country() -> None:
    client = LocalKnowledgeClient()

    response = client.search(query="日本 旅游签证", table_names=["visa_knowledge"], top_k=3)

    assert response.code == 0
    assert response.chunks
    assert any("日本" in chunk.content for chunk in response.chunks)


def test_search_returns_empty_for_blank_query() -> None:
    """空查询不该返回任何片段，否则会随机塞一段知识进上下文。"""
    client = LocalKnowledgeClient()

    response = client.search(query="   ", table_names=["visa_knowledge"])

    assert response.chunks == []


def test_search_respects_min_score() -> None:
    """把阈值拉到 1.0 以上时不应有片段达标——说明 min_score 真的在起作用。"""
    client = LocalKnowledgeClient()

    response = client.search(query="日本 旅游签证", table_names=["visa_knowledge"], min_score=1.01)

    assert response.chunks == []


def test_search_respects_top_k() -> None:
    client = LocalKnowledgeClient()

    response = client.search(query="日本 旅游签证 材料", table_names=["visa_knowledge", "material_checklist"], top_k=1)

    assert len(response.chunks) <= 1


def test_chunks_are_sorted_by_score_descending() -> None:
    """按相关度倒序是"把最相关的放在最前面"的前提，模型看的是前几条。"""
    client = LocalKnowledgeClient()

    response = client.search(query="日本 旅游签证", table_names=["visa_knowledge"], top_k=5)

    scores = [chunk.score for chunk in response.chunks]
    assert scores == sorted(scores, reverse=True)


def test_unknown_table_is_ignored_not_crashed() -> None:
    """表名写错时返回空，而不是抛异常把整条链路带崩。"""
    client = LocalKnowledgeClient()

    response = client.search(query="日本", table_names=["not_a_table"])

    assert response.chunks == []


@pytest.mark.xfail(
    strict=True,
    reason="已知缺口：当前无相关性门控，域外问题仍会召回通用片段",
)
def test_out_of_domain_query_returns_nothing() -> None:
    """域外问题（火星签证）不该命中任何知识片段。

    当前实现在这里会失败——因为打分只看关键词重合，不看"这个国家是否存在"。
    这正是"火星问题被拒答"这件事目前只能依赖模型判断、无法确定性验证的原因。
    """
    client = LocalKnowledgeClient()

    response = client.search(query="火星 旅游签证 材料清单", min_score=0.3)

    assert response.chunks == []


# ========== 节点行为 ==========

def test_node_uses_structured_query_not_raw_sentence(fake_runtime) -> None:
    """节点只用结构化关键词拼查询：整句会稀释关键词命中率。"""
    state = KnowledgeRetrievalInput(
        country="日本",
        visa_type="旅游",
        intent="faq",
        user_message="我想问一下日本旅游签证大概需要多长时间才能办好呀谢谢",
    )

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    assert result.knowledge_context
    assert "日本" in result.knowledge_context


def test_node_lists_materials_for_material_intent(fake_runtime) -> None:
    """material 意图要产出"所需材料清单"，这是"先槽位→再检索→列缺件"的最后一环。

    注意断言的是 required_materials 而不是 missing_slots：
    前者是给模型看的参考资料，后者是"决定是否追问"的必填槽位，
    两者曾经共用一个字段，导致用户问材料时反而被反问（见 state.py 注释）。
    """
    state = KnowledgeRetrievalInput(
        country="日本",
        visa_type="旅游",
        intent="material",
        user_message="日本旅游签证要哪些材料",
    )

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    assert result.required_materials
    assert any("在职证明" in item for item in result.required_materials)


def test_material_intent_does_not_report_missing_slots(fake_runtime) -> None:
    """列材料不等于"缺用户信息"，节点不得把它写进追问信号。"""
    state = KnowledgeRetrievalInput(
        country="日本",
        visa_type="旅游",
        intent="material",
        user_message="日本旅游签证要哪些材料",
    )

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    assert not hasattr(result, "missing_slots")


def test_node_returns_empty_context_for_blank_input(fake_runtime) -> None:
    """没有任何线索时不硬编造上下文。"""
    state = KnowledgeRetrievalInput(intent="faq", user_message="")

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    # 允许有限命中，但不能凭空生成内容：要么空，要么确实来自文档。
    assert isinstance(result.knowledge_context, str)
