from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.domain.enums import KnowledgeNodeSource, KnowledgeNodeType
from app.schemas.graph import GraphNodeCreate
from app.services.ai_router import AIRouter


class BusinessContext(BaseModel):
    summary: str
    keywords: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)


class ExtractorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ai_router = AIRouter(settings)

    async def detect_business_context(self, raw_text: str) -> BusinessContext:
        summary = self._summarize_text(raw_text)
        keywords = self._extract_keywords(raw_text)
        queries = [f"{keyword} market size indonesia" for keyword in keywords[:2]]
        return BusinessContext(summary=summary, keywords=keywords, search_queries=queries)

    async def extract_nodes_from_text(self, raw_text: str) -> list[GraphNodeCreate]:
        if self.settings.effective_ai_provider != "stub":
            try:
                route = await asyncio.to_thread(
                    self.ai_router.complete_json,
                    use_case="extraction",
                    system_prompt=(
                        "Extract flat business-case graph nodes from text. "
                        "Return JSON with key 'nodes', where each node has type, title, description."
                    ),
                    user_prompt=raw_text[:8000],
                )
                payload = route.payload.get("nodes", [])
                if isinstance(payload, list):
                    nodes = []
                    for item in payload[:12]:
                        if not isinstance(item, dict):
                            continue
                        nodes.append(
                            GraphNodeCreate(
                                type=KnowledgeNodeType(str(item.get("type", "problem"))),
                                title=str(item.get("title", "Untitled node"))[:255],
                                description=str(item.get("description", ""))[:4000] or None,
                                source=KnowledgeNodeSource.DOCUMENT,
                            )
                        )
                    if nodes:
                        return self._with_positions(nodes)
            except Exception:
                pass

        paragraphs = self._extract_candidate_paragraphs(raw_text)
        nodes = [
            GraphNodeCreate(
                type=self._infer_type(paragraph),
                title=self._title_for_paragraph(paragraph),
                description=paragraph[:4000],
                source=KnowledgeNodeSource.DOCUMENT,
            )
            for paragraph in paragraphs[:10]
        ]
        if not nodes:
            nodes = [
                GraphNodeCreate(
                    type=KnowledgeNodeType.PROBLEM,
                    title="Uploaded business case",
                    description=self._summarize_text(raw_text),
                    source=KnowledgeNodeSource.DOCUMENT,
                )
            ]
        return self._with_positions(nodes)

    def _extract_candidate_paragraphs(self, raw_text: str) -> list[str]:
        blocks = re.split(r"\n\s*\n", raw_text)
        cleaned = [re.sub(r"\s+", " ", block).strip(" -•\t\r\n") for block in blocks]
        return [block for block in cleaned if len(block) >= 24]

    def _summarize_text(self, raw_text: str) -> str:
        normalized = re.sub(r"\s+", " ", raw_text).strip()
        return normalized[:280] or "Business case document"

    def _extract_keywords(self, raw_text: str) -> list[str]:
        words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", raw_text.lower())
        stopwords = {"this", "that", "with", "from", "have", "will", "your", "their", "about", "problem", "solution"}
        keywords: list[str] = []
        for word in words:
            if word in stopwords or word in keywords:
                continue
            keywords.append(word)
        return keywords[:6]

    def _infer_type(self, paragraph: str) -> KnowledgeNodeType:
        lowered = paragraph.lower()
        mapping: list[tuple[str, KnowledgeNodeType]] = [
            ("risk", KnowledgeNodeType.RISK),
            ("opportunity", KnowledgeNodeType.OPPORTUNITY),
            ("assumption", KnowledgeNodeType.ASSUMPTION),
            ("metric", KnowledgeNodeType.METRIC),
            ("stakeholder", KnowledgeNodeType.STAKEHOLDER),
            ("constraint", KnowledgeNodeType.CONSTRAINT),
            ("regulation", KnowledgeNodeType.REGULATION),
            ("competitor", KnowledgeNodeType.COMPETITOR),
            ("trend", KnowledgeNodeType.TREND),
            ("market", KnowledgeNodeType.MARKET_DATA),
            ("evidence", KnowledgeNodeType.EVIDENCE),
            ("objective", KnowledgeNodeType.OBJECTIVE),
            ("resource", KnowledgeNodeType.RESOURCE),
            ("solution", KnowledgeNodeType.SOLUTION),
            ("problem", KnowledgeNodeType.PROBLEM),
        ]
        for keyword, node_type in mapping:
            if keyword in lowered:
                return node_type
        return KnowledgeNodeType.PROBLEM

    def _title_for_paragraph(self, paragraph: str) -> str:
        sentence = paragraph.split(".")[0].strip()
        return sentence[:120] if sentence else paragraph[:120]

    def _with_positions(self, nodes: list[GraphNodeCreate]) -> list[GraphNodeCreate]:
        positioned: list[GraphNodeCreate] = []
        for index, node in enumerate(nodes):
            positioned.append(
                node.model_copy(
                    update={
                        "position": {
                            "x": float((index % 4) * 320),
                            "y": float((index // 4) * 180),
                        }
                    }
                )
            )
        return positioned
