from __future__ import annotations

from app.core.config import Settings
from app.domain.enums import KnowledgeNodeSource, KnowledgeNodeType
from app.schemas.graph import GraphNodeCreate
from app.services.extractor import BusinessContext


class ScraperService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def enrich_from_context(self, context: BusinessContext) -> list[GraphNodeCreate]:
        keyword = context.keywords[0] if context.keywords else "industry"
        query = context.search_queries[0] if context.search_queries else f"{keyword} market outlook"
        base_url = f"https://example.com/search?q={query.replace(' ', '+')}"
        return [
            GraphNodeCreate(
                type=KnowledgeNodeType.MARKET_DATA,
                title=f"{keyword.title()} market signal",
                description=f"Contextual market data enrichment for {keyword}.",
                source=KnowledgeNodeSource.WEB,
                is_enrichment=True,
                source_url=base_url,
            ),
            GraphNodeCreate(
                type=KnowledgeNodeType.TREND,
                title=f"{keyword.title()} trend watch",
                description=f"External trend signal inferred from the uploaded context: {context.summary[:180]}",
                source=KnowledgeNodeSource.WEB,
                is_enrichment=True,
                source_url=f"{base_url}&type=trend",
            ),
            GraphNodeCreate(
                type=KnowledgeNodeType.COMPETITOR,
                title=f"{keyword.title()} competitor benchmark",
                description=f"Competitive context enrichment generated for {keyword}.",
                source=KnowledgeNodeSource.WEB,
                is_enrichment=True,
                source_url=f"{base_url}&type=competitor",
            ),
        ]
