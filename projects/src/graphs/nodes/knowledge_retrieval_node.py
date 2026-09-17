"""知识库检索节点 - material意图先槽位后检索+列缺件"""
import logging
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from utils.context import Context
from utils.knowledge import LocalKnowledgeClient
from graphs.state import KnowledgeRetrievalInput, KnowledgeRetrievalOutput

logger = logging.getLogger(__name__)


def knowledge_retrieval_node(
    state: KnowledgeRetrievalInput,
    config: RunnableConfig,
    runtime: Runtime[Context]
) -> KnowledgeRetrievalOutput:
    """
    title: 知识库检索
    desc: 根据意图和已提取的关键信息（国家/签证类型），从本地知识库（assets/*.md）检索签证信息。material意图会额外分析所需材料清单并输出缺失材料列表，实现"先槽位→再检索→列缺件"的流程。
    integrations: 知识库
    """
    _ = runtime.context

    # 构建检索query（只用结构化关键词，不拼原始 user_message：
    # 本地关键词检索对整句/标点敏感，整句会稀释命中率）
    query_parts = []
    if state.country:
        query_parts.append(state.country)
    if state.visa_type:
        query_parts.append(state.visa_type)
    if state.intent == "material":
        query_parts.append("材料清单")
    elif state.intent == "faq":
        query_parts.append("签证政策")

    # 去重并拼接
    seen = set()
    unique_parts = []
    for p in query_parts:
        if p and p not in seen:
            seen.add(p)
            unique_parts.append(p)
    query = " ".join(unique_parts) if unique_parts else state.user_message

    required_materials = []

    try:
        knowledge_client = LocalKnowledgeClient()
        search_response = knowledge_client.search(
            query=query,
            table_names=["visa_knowledge", "material_checklist"],
            top_k=5,
            min_score=0.3
        )

        if search_response.code == 0 and search_response.chunks:
            knowledge_pieces = []
            for i, chunk in enumerate(search_response.chunks):
                score = chunk.score if hasattr(chunk, "score") else 0
                content = chunk.content if hasattr(chunk, "content") else ""
                if content:
                    knowledge_pieces.append(f"[知识片段{i+1}](相关度: {score:.2f})\n{content}")

            knowledge_context = "\n\n---\n\n".join(knowledge_pieces)

            # material意图：列出该签证类型的所需材料，供回复生成引用。
            # 这是"参考资料"而不是"缺失信息"，不能写进 missing_slots，
            # 否则风控会把它当成"还需要追问用户"（见 KnowledgeRetrievalOutput 的注释）。
            if state.intent == "material":
                required_materials = _analyze_missing_materials(
                    state.country, state.visa_type, knowledge_context
                )
        else:
            knowledge_context = ""
            logger.warning(f"知识库搜索无结果, code={search_response.code}, query={query}")

    except Exception as e:
        logger.error(f"知识库检索异常: {str(e)}")
        knowledge_context = ""

    return KnowledgeRetrievalOutput(
        knowledge_context=knowledge_context,
        required_materials=required_materials,
    )


def _analyze_missing_materials(
    country: str,
    visa_type: str,
    knowledge_context: str
) -> list:
    """
    分析material意图下用户可能缺失的材料。
    基于知识库检索到的材料清单，生成所需材料列表。
    由于用户未提供个人情况，这里列出该签证类型的通用必备材料供参考。
    """
    missing = []

    # 通用必备材料（所有签证类型都需要）
    universal_materials = [
        "有效护照（有效期超过行程结束后6个月）",
        "近6个月白底彩色证件照",
        "签证申请表"
    ]

    # 根据签证类型的额外材料
    type_materials = {
        "旅游": [
            "在职证明",
            "近6个月银行流水",
            "行程计划表",
            "机票预订单",
            "酒店预订单"
        ],
        "商务": [
            "邀请函",
            "派遣函",
            "双方营业执照",
            "商务往来证明"
        ],
        "学生": [
            "录取通知书",
            "资金证明",
            "语言成绩单",
            "体检报告"
        ]
    }

    # 添加通用材料
    missing.extend(universal_materials)

    # 根据签证类型添加额外材料
    matched_type = None
    for key in type_materials:
        if key in (visa_type or ""):
            matched_type = key
            break

    if matched_type:
        missing.extend(type_materials[matched_type])
    elif country:
        # 如果未匹配到具体类型，列出所有类型的材料供参考
        missing.append("（请根据具体签证类型准备对应材料）")

    return missing
