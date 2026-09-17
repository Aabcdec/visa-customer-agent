"""本地知识库检索 - 替代 coze_coding_dev_sdk.KnowledgeClient。

为什么自建：去掉 Coze 依赖后，知识库检索节点需要一个本地实现。这里把
assets/ 下的 markdown 文档按二级标题（## ）分节，用关键词命中打分，
返回与 Coze search 接口兼容的结果（code/chunks/score/content），
节点代码几乎无需改动。

数据源：
- assets/countries_faq.md      各国签证 FAQ
- assets/material_checklist.md 签证材料清单
- assets/risk_policy.md        风险评估政策
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 项目根 = 本文件所在目录的上三级（src/utils/llm.py -> projects/）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 知识库文档清单（表名 -> 文件相对路径）
DEFAULT_TABLES: Dict[str, str] = {
    "visa_knowledge": "assets/countries_faq.md",
    "material_checklist": "assets/material_checklist.md",
    "risk_policy": "assets/risk_policy.md",
}

# 国别别名 -> 知识库使用的正式写法。
#
# 为什么需要：门控的判据是"该国家名是否真的出现在文档里"，而用户/模型可能给出
# 口语简称（美签、澳洲）。不归一化就会把合法国家误判成域外，把能答的问题拒掉。
COUNTRY_ALIASES: Dict[str, str] = {
    "美签": "美国",
    "日签": "日本",
    "韩签": "韩国",
    "英签": "英国",
    "澳洲": "澳大利亚",
    "申根国": "申根",
    "申根国家": "申根",
    "欧洲": "申根",
    # 申根成员国：这些国家共用同一套申根签证规则，知识库以"申根"统一收录。
    # 不做映射会让"法国签证怎么办"被判成域外而拒答，属于不必要的误拒。
    # 注意：爱尔兰不是申根国、英国有自己的签证体系，二者都不能映射。
    "法国": "申根",
    "德国": "申根",
    "意大利": "申根",
    "西班牙": "申根",
    "荷兰": "申根",
    "瑞士": "申根",
    "瑞典": "申根",
    "挪威": "申根",
    "丹麦": "申根",
    "芬兰": "申根",
    "葡萄牙": "申根",
    "希腊": "申根",
    "比利时": "申根",
    "奥地利": "申根",
    "冰岛": "申根",
    "卢森堡": "申根",
    "波兰": "申根",
    "捷克": "申根",
    "匈牙利": "申根",
}

# 单个术语的匹配用不区分大小写（中文不受影响，但兼容英文字段如 DS-160）
# 按长度倒序，保证长别名先替换：
# 否则"申根国家"会先被"申根国"命中，替换成"申根家"这种残缺词。
_ALIAS_PAIRS_LONGEST_FIRST = sorted(COUNTRY_ALIASES.items(), key=lambda kv: -len(kv[0]))


def _apply_aliases(text: str) -> str:
    """把文本里的国别口语简称替换为知识库使用的正式写法。

    查询串与门控术语都必须走这一步：门控把"美签"归一化成"美国"后能选中章节，
    但如果查询串仍写着"美签"，打分阶段就因关键词不匹配而拿不到分，
    结果依然检索不到——两边必须用同一套归一化。
    """
    result = text
    for alias, canonical in _ALIAS_PAIRS_LONGEST_FIRST:
        if alias in result:
            result = result.replace(alias, canonical)
    return result


def _normalize_terms(terms: Optional[List[str]]) -> List[str]:
    """把国别术语归一化为知识库里的正式写法，并去重去空。"""
    normalized: List[str] = []
    for term in terms or []:
        if not term:
            continue
        canonical = _apply_aliases(term.strip())
        if canonical and canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _section_contains_all_terms(section: Dict[str, Any], terms: List[str]) -> bool:
    """判断某个文档节是否同时包含全部必需术语（大小写不敏感）。

    用"同时包含全部"而不是"包含任一"：查询里若同时出现国家和主题词，
    只有两者都命中的章节才是真正相关的依据。
    """
    if not terms:
        return True
    haystack = f"{section.get('title', '')}\n{section.get('content', '')}".lower()
    return all(term.lower() in haystack for term in terms)


@dataclass
class Chunk:
    """单个检索片段，兼容原 SDK 的 chunk.score / chunk.content 访问。"""

    content: str
    score: float = 0.0


@dataclass
class SearchResponse:
    """检索响应，兼容原 SDK 的 code / chunks 访问。"""

    code: int = 0
    chunks: List[Chunk] = field(default_factory=list)


class LocalKnowledgeClient:
    """本地 markdown 知识库检索。

    使用方式与原 KnowledgeClient 一致：
        client = LocalKnowledgeClient(config=..., ctx=...)
        resp = client.search(query=..., table_names=["visa_knowledge"], top_k=5)
    """

    def __init__(self, config: Any = None, ctx: Any = None) -> None:
        self.config = config
        self.ctx = ctx
        self._docs: Dict[str, List[Dict[str, Any]]] = {}
        self._table_files = dict(DEFAULT_TABLES)

    def _load_table(self, table_name: str) -> List[Dict[str, Any]]:
        """读取并分节一个 markdown 文档，返回 [{title, content, keywords}]。"""
        if table_name in self._docs:
            return self._docs[table_name]

        rel_path = self._table_files.get(table_name)
        if not rel_path:
            logger.warning(f"未知知识库表: {table_name}，跳过")
            self._docs[table_name] = []
            return self._docs[table_name]

        # 兼容 COZE_WORKSPACE_PATH 环境变量（若设置了则优先）
        workspace = os.getenv("COZE_WORKSPACE_PATH", "")
        if workspace:
            path = Path(workspace) / rel_path
        else:
            path = PROJECT_ROOT / rel_path

        sections: List[Dict[str, Any]] = []
        if not path.exists():
            logger.warning(f"知识库文件不存在: {path}")
            self._docs[table_name] = sections
            return sections

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"读取知识库文件失败 {path}: {e}")
            self._docs[table_name] = sections
            return sections

        # 按二级标题分节（## ），保留标题和正文
        lines = text.splitlines()
        current_title = ""
        current_body: List[str] = []
        pending_heading = ""  # 记录一级标题（# ），作为文档主题

        def flush() -> None:
            nonlocal current_title, current_body
            if current_title and current_body:
                content = "\n".join(current_body).strip()
                if content:
                    sections.append(
                        {
                            "title": current_title,
                            "content": content,
                            "keywords": _extract_keywords(f"{current_title}\n{content}"),
                        }
                    )
            current_body = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## "):
                flush()
                current_title = stripped[3:].strip()
            elif stripped.startswith("# ") and not current_title:
                pending_heading = stripped[2:].strip()
            elif current_title:
                current_body.append(line)
            elif pending_heading:
                # 一级标题下的引言，暂存（通常很短）
                current_body.append(line)
        flush()

        self._docs[table_name] = sections
        logger.info(f"知识库 {table_name} 加载完成: {len(sections)} 节")
        return sections

    def search(
        self,
        query: str,
        table_names: Optional[List[str]] = None,
        top_k: int = 5,
        min_score: float = 0.3,
        required_terms: Optional[List[str]] = None,
        **_: Any,
    ) -> SearchResponse:
        """关键词检索：对每个文档节按查询词命中打分，返回 top_k。

        参数:
            required_terms: 必须出现在文档节里的术语（通常是国家名）。
                这是"域外问题门控"：知识库只覆盖有限国家，但关键词打分不看
                "这个实体是否存在"，导致"火星签证"会命中别国的通用材料章节，
                系统于是拿着日本签证的资料回答火星的问题。

                加上门控后，域外问题会得到零依据——"不编造"从"靠模型自觉"
                变成"结构上做不到"。不传该参数时保持原有行为。
        """
        if not query or not query.strip():
            return SearchResponse(code=0, chunks=[])

        tables = table_names or list(self._table_files.keys())
        # 查询串与门控术语共用同一套别名归一化，避免"门控选中了章节、
        # 打分却因简称不匹配拿不到分"这种自相矛盾的结果。
        normalized_query = _apply_aliases(query)
        query_lower = normalized_query.lower()
        query_terms = _extract_keywords(normalized_query)
        must_have = _normalize_terms(required_terms)

        scored: List[Chunk] = []
        for table in tables:
            for section in self._load_table(table):
                # 门控前置：不满足必需术语的章节直接不参与打分，
                # 避免它靠通用词（"签证""材料"）拿到虚高分数。
                if not _section_contains_all_terms(section, must_have):
                    continue
                score = _score_section(section, query_lower, query_terms)
                if score >= min_score:
                    content = f"【{section['title']}】\n{section['content']}"
                    scored.append(Chunk(content=content, score=round(score, 2)))

        scored.sort(key=lambda c: c.score, reverse=True)
        return SearchResponse(code=0, chunks=scored[:top_k])


def _extract_keywords(text: str) -> List[str]:
    """从文本中提取检索关键词：国家名、签证类型词、通用主题词。"""
    keywords: List[str] = []
    for m in re.findall(r"[\u4e00-\u9fa5]{2,8}", text):
        if m not in keywords:
            keywords.append(m)
    return keywords


def _score_section(section: Dict[str, Any], query_lower: str, query_terms: List[str]) -> float:
    """计算文档节与查询的相关度得分（0~1）。

    打分逻辑：
    - 整段包含查询词（空格分隔的语义片段）命中数占比，主分
    - 节标题命中额外加权（标题命中说明该节就是查的那个主题）
    """
    title = section.get("title", "").lower()
    content = section.get("content", "").lower()
    text = f"{title}\n{content}"

    # 语义片段（节点按空格拼接，如 "日本 旅游签证 签证政策 ..."）
    segments = [s for s in query_lower.split() if s]
    if not segments:
        return 0.0

    # 完整片段命中：该片段原文出现在文本中（如 "旅游签证"）
    hits = sum(1 for seg in segments if seg in text)
    hit_ratio = hits / len(segments)

    # 标题命中加权：任一语义片段出现在标题中，视为强相关
    title_hits = sum(1 for seg in segments if seg in title)
    title_ratio = title_hits / len(segments) if segments else 0.0

    # 2-8 字词粒度的补充命中（覆盖片段含标点/混排的场景）
    word_hits = sum(1 for t in query_terms if t and t in text)
    word_ratio = word_hits / len(query_terms) if query_terms else 0.0

    score = 0.5 * hit_ratio + 0.4 * title_ratio + 0.1 * word_ratio
    return min(1.0, score)
