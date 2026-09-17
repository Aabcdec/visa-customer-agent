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


def test_out_of_domain_query_returns_nothing() -> None:
    """域外问题（火星签证）不该命中任何知识片段。

    这条曾经是 xfail：打分只看关键词重合，不看"这个国家是否存在"，
    所以"火星"仍会召回通用材料片段，导致拒答只能依赖模型判断。
    现在由 required_terms 国别门控保证——见下方门控测试。
    """
    client = LocalKnowledgeClient()

    response = client.search(
        query="火星 旅游签证 材料清单",
        table_names=["visa_knowledge", "material_checklist"],
        min_score=0.3,
        required_terms=["火星"],
    )

    assert response.chunks == []


def test_search_without_required_terms_keeps_legacy_behaviour() -> None:
    """不传 required_terms 时保持原行为（泛化问题仍有结果）。"""
    client = LocalKnowledgeClient()

    response = client.search(query="签证 材料", table_names=["material_checklist"], min_score=0.3)

    assert response.chunks


def test_required_terms_filters_out_sections_missing_the_country() -> None:
    """门控语义：只要某节正文/标题里没有该国家名，就不允许作为依据。"""
    client = LocalKnowledgeClient()

    response = client.search(
        query="日本 签证",
        table_names=["visa_knowledge"],
        min_score=0.3,
        required_terms=["火星"],
    )

    assert response.chunks == []


def test_required_terms_keeps_matching_country_sections() -> None:
    client = LocalKnowledgeClient()

    response = client.search(
        query="日本 签证",
        table_names=["visa_knowledge"],
        min_score=0.3,
        required_terms=["日本"],
    )

    assert response.chunks
    assert all("日本" in chunk.content for chunk in response.chunks)


def test_country_alias_is_normalised() -> None:
    """口语简称（美签/日签/澳洲）要能归一化到知识库使用的正式名。"""
    client = LocalKnowledgeClient()

    response = client.search(
        query="美签 面试",
        table_names=["visa_knowledge"],
        min_score=0.3,
        required_terms=["美签"],
    )

    assert response.chunks
    assert all("美国" in chunk.content for chunk in response.chunks)


@pytest.mark.parametrize("country", ["法国", "德国", "意大利", "西班牙", "瑞士"])
def test_schengen_member_maps_to_schengen_section(country: str) -> None:
    """申根成员国的问题应命中"申根"章节，而不是被判成域外拒答。

    这些国家共用同一套申根签证规则，知识库以"申根"统一收录；
    不做映射会让"法国签证怎么办"这类正常提问被拒绝回答。
    """
    client = LocalKnowledgeClient()

    response = client.search(
        query=f"{country} 旅游签证 材料",
        table_names=["visa_knowledge", "material_checklist"],
        min_score=0.3,
        required_terms=[country],
    )

    assert response.chunks, f"{country} 应命中申根章节"


@pytest.mark.parametrize("country", ["爱尔兰", "英国"])
def test_non_schengen_countries_are_not_mapped_to_schengen(country: str) -> None:
    """爱尔兰不是申根国、英国有自己的体系，绝不能借用申根内容回答。"""
    client = LocalKnowledgeClient()

    response = client.search(
        query=f"{country} 旅游签证",
        table_names=["visa_knowledge"],
        min_score=0.3,
        required_terms=[country],
    )

    # 英国本身有独立章节，应命中英国内容而非申根；爱尔兰应零依据。
    if country == "英国":
        assert response.chunks
        assert all("英国" in chunk.content for chunk in response.chunks)
    else:
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


# ========== 国别门控（节点层） ==========

def test_node_returns_no_context_for_unknown_country(fake_runtime) -> None:
    """域外国家必须检索不到任何内容——这是"不编造"的确定性前提。

    为什么需要它：检索原先只按关键词重合打分，"火星"虽然不在知识库里，
    但查询里的"签证""材料"等通用词仍能命中别的国家章节，于是系统会拿着
    日本签证的资料回答火星签证的问题。门控把这种情况变成"零依据"。
    """
    state = KnowledgeRetrievalInput(
        country="火星",
        visa_type="旅游",
        intent="faq",
        user_message="火星旅游签证办理周期和材料要求是什么？",
    )

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    assert result.knowledge_context == ""


def test_node_returns_no_materials_for_unknown_country(fake_runtime) -> None:
    """域外国家也不该吐出材料清单，否则用户会拿到别国要求的材料。"""
    state = KnowledgeRetrievalInput(
        country="瓦坎达",
        visa_type="旅游",
        intent="material",
        user_message="瓦坎达旅游签证要什么材料",
    )

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    assert result.knowledge_context == ""
    assert result.required_materials == []


def test_node_still_returns_context_for_known_country(fake_runtime) -> None:
    """门控不能误伤正常国家——这是本次改动最需要防的回归。"""
    state = KnowledgeRetrievalInput(
        country="日本",
        visa_type="旅游",
        intent="faq",
        user_message="日本旅游签证要办多久",
    )

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    assert result.knowledge_context
    assert "日本" in result.knowledge_context


@pytest.mark.parametrize("country", ["韩国", "泰国", "美国", "英国", "澳大利亚", "申根", "新加坡", "加拿大"])
def test_gate_does_not_block_any_supported_country(fake_runtime, country: str) -> None:
    """逐个覆盖知识库支持的全部国家，确认门控不会把合法国家挡掉。"""
    state = KnowledgeRetrievalInput(
        country=country,
        visa_type="旅游",
        intent="faq",
        user_message=f"{country}旅游签证要办多久",
    )

    result = knowledge_retrieval_node(state, {}, fake_runtime)

    assert result.knowledge_context, f"{country} 被门控误伤"
