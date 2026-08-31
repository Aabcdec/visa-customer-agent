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
        **_: Any,
    ) -> SearchResponse:
        """关键词检索：对每个文档节按查询词命中打分，返回 top_k。"""
        if not query or not query.strip():
            return SearchResponse(code=0, chunks=[])

        tables = table_names or list(self._table_files.keys())
        query_lower = query.lower()
        query_terms = _extract_keywords(query)

        scored: List[Chunk] = []
        for table in tables:
            for section in self._load_table(table):
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
