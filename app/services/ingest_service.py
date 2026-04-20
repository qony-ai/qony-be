from __future__ import annotations

import asyncio
from collections import defaultdict
import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.security import Actor
from app.domain.enums import IngestJobStatus, UsageEventType
from app.repositories.ingest_jobs import IngestJobRepository
from app.repositories.projects import ProjectRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.ingest import ingest_job_to_read
from app.services.extractor import ExtractorService
from app.services.graph_engine import GraphEngine
from app.services.scraper import ScraperService
from app.services.usage_service import UsageService
from app.utils.document_parser import parse_document

logger = logging.getLogger(__name__)


class IngestProgressBroker:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._terminal_events: dict[str, dict] = {}

    async def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[job_id].append(queue)
        terminal = self._terminal_events.get(job_id)
        if terminal is not None:
            await queue.put(terminal)
        return queue

    async def publish(self, job_id: str, event: dict) -> None:
        if event.get("event") in {"complete", "failed"}:
            self._terminal_events[job_id] = event
        for queue in list(self._queues.get(job_id, [])):
            await queue.put(event)

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        listeners = self._queues.get(job_id, [])
        if queue in listeners:
            listeners.remove(queue)
        if not listeners and job_id in self._queues:
            self._queues.pop(job_id, None)


progress_broker = IngestProgressBroker()


class PRDIngestionService:
    def __init__(self, *, session: Session, settings: Settings, actor: Actor) -> None:
        self.session = session
        self.settings = settings
        self.actor = actor
        self.user_repository = UserRepository(session)
        self.project_repository = ProjectRepository(session)
        self.workspace_repository = WorkspaceRepository(session)
        self.ingest_job_repository = IngestJobRepository(session)
        self.extractor = ExtractorService(settings)
        self.scraper = ScraperService(settings)
        self.graph_engine = GraphEngine(session=session, settings=settings, actor=actor)
        self.usage_service = UsageService(session=session, actor=actor)

    def create_job(
        self,
        *,
        project_id,
        source_filename: str | None,
        source_content_type: str | None,
        metadata: dict | None = None,
    ):
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        project = self._resolve_project(project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        workspace = self.workspace_repository.get_by_project_id(project.id)
        if workspace is None:
            workspace = self.workspace_repository.create_for_project(
                project_id=project.id,
                metadata={"created_by": self.actor.email},
            )
            self.session.flush()

        job = self.ingest_job_repository.create_pending(
            project_id=project.id,
            workspace_id=workspace.id,
            requested_by_user_id=user.id,
            raw_text="",
            source_filename=source_filename,
            source_content_type=source_content_type,
            provider=self.settings.effective_ai_provider,
            metadata=metadata or {},
        )
        self.session.commit()
        return ingest_job_to_read(job)

    async def process_document(self, *, file_path: str, project_id, job_id) -> None:
        project = self._resolve_project(project_id)
        if project is None:
            await progress_broker.publish(
                str(job_id),
                {"event": "failed", "message": "Project not found"},
            )
            return

        job_model = self.session.get(self.ingest_job_repository.model_class, job_id)
        if job_model is not None:
            job_model.status = IngestJobStatus.PROCESSING.value
            self.session.commit()

        await progress_broker.publish(str(job_id), {"event": "progress", "step": "parsing", "pct": 10})
        raw_text = await parse_document(file_path)

        await progress_broker.publish(
            str(job_id),
            {"event": "progress", "step": "context_detection", "pct": 20},
        )
        context = await self.extractor.detect_business_context(raw_text)

        await progress_broker.publish(
            str(job_id),
            {"event": "progress", "step": "extracting_nodes", "pct": 40},
        )
        await progress_broker.publish(
            str(job_id),
            {"event": "progress", "step": "scraping_internet", "pct": 60},
        )

        doc_nodes, web_nodes = await asyncio.gather(
            self.extractor.extract_nodes_from_text(raw_text),
            self.scraper.enrich_from_context(context),
            return_exceptions=True,
        )

        if isinstance(doc_nodes, Exception):
            logger.error("document extraction failed", exc_info=doc_nodes)
            await progress_broker.publish(
                str(job_id),
                {"event": "failed", "message": "Document extraction failed"},
            )
            raise doc_nodes

        if isinstance(web_nodes, Exception):
            logger.warning("scraping failed during ingest", exc_info=web_nodes)
            web_nodes = []

        await progress_broker.publish(
            str(job_id),
            {"event": "progress", "step": "building_graph", "pct": 85},
        )
        graph = self.graph_engine.ingest_graph(
            project_id=project.id,
            nodes=[*doc_nodes, *web_nodes],
            metadata={
                "ingest_mode": "parallel_document_plus_web",
                "context_summary": context.summary,
                "source_path": file_path,
            },
        )

        job_model = self.session.get(self.ingest_job_repository.model_class, job_id)
        if job_model is not None:
            job_model.status = IngestJobStatus.COMPLETED.value
            job_model.provider = self.settings.effective_ai_provider
            job_model.model = self.settings.model_for_use_case("extraction")
            job_model.fallback_used = False
            job_model.raw_text = raw_text[:12000]
            job_model.output_graph_json = graph.model_dump(mode="json")
            self.session.commit()

        self.usage_service.record_event(
            event_type=UsageEventType.SCRAPE,
            project_id=project.id,
            quantity=len(web_nodes),
            metadata={"job_id": str(job_id)},
        )
        self.session.commit()

        await progress_broker.publish(
            str(job_id),
            {"event": "complete", "graph_id": str(graph.id), "node_count": len(graph.nodes)},
        )

    def _resolve_project(self, project_id):
        if self.actor.source == "default":
            return self.project_repository.get_by_id(project_id)
        user = self.user_repository.get_or_create(
            email=self.actor.email,
            name=self.actor.name,
            external_auth_id=self.actor.auth_user_id,
        )
        return self.project_repository.get_for_user(project_id, user.id)
