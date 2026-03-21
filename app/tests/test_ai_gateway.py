from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.enums import NodeRank
from app.integrations.ai.factory import build_ai_adapter
from app.services.ai_service import AIService


def test_ai_provider_factory_selects_stub():
    settings = Settings(database_url="sqlite:///./factory-test.db", ai_provider="stub")
    provider = build_ai_adapter(settings)
    assert provider.provider == "stub"


def test_ai_service_falls_back_to_stub_when_remote_is_unavailable(app, test_settings):
    test_settings.ai_provider = "remote"
    test_settings.remote_ai_base_url = "http://127.0.0.1:1"
    test_settings.remote_ai_api_key = "test-key"

    with Session(app.state.engine) as session:
        service = AIService(
            session=session,
            settings=test_settings,
            actor=type("Actor", (), {"email": "tester@qony.ai", "name": "Tester"})(),
        )
        suggestion = service.generate_ingest_graph(
            project_id=UUID("00000000-0000-0000-0000-000000000001"),
            workspace_id=UUID("00000000-0000-0000-0000-000000000002"),
            user_id=UUID("00000000-0000-0000-0000-000000000003"),
            raw_text="Customer churn is rising while expansion revenue is flat.",
            workspace_version=1,
        )

    assert suggestion.provider_result.provider == "remote"
    assert suggestion.provider_result.fallback_used is True
    assert suggestion.graph.nodes
    assert suggestion.graph.metadata.attributes["ingest_mode"] == "stub_fallback"
    assert suggestion.graph.metadata.attributes["provider_attempted"] == "remote"


def test_stub_ingest_graph_splits_problem_bullets_into_multiple_branches(app, test_settings):
    raw_text = """
    BUSINESS CASE
    Implementasi Sistem Inventory & Procurement Digital
    Inti rekomendasi: lanjutkan implementasi bertahap untuk memperbaiki kontrol stok dan pembelian.

    1. Latar belakang & masalah
    Saat ini proses monitoring stok dan approval pembelian masih mengandalkan spreadsheet terpisah.
    - Stockout pada item fast-moving menyebabkan lost sales dan mengganggu service level.
    - Tim operasional menghabiskan banyak waktu untuk rekonsiliasi data stok dan follow-up approval.
    - Pembelian darurat meningkatkan biaya dan membuat vendor planning tidak stabil.

    2. Manfaat
    Sistem baru diharapkan mempercepat approval dan meningkatkan visibilitas stok.
    """

    with Session(app.state.engine) as session:
        service = AIService(
            session=session,
            settings=test_settings,
            actor=type("Actor", (), {"email": "tester@qony.ai", "name": "Tester"})(),
        )
        suggestion = service.generate_ingest_graph(
            project_id=UUID("00000000-0000-0000-0000-000000000001"),
            workspace_id=UUID("00000000-0000-0000-0000-000000000002"),
            user_id=UUID("00000000-0000-0000-0000-000000000003"),
            raw_text=raw_text,
            workspace_version=1,
        )

    root = next(node for node in suggestion.graph.nodes if node.rank == NodeRank.PROBLEM_STATEMENT)
    sub_problems = [node for node in suggestion.graph.nodes if node.rank == NodeRank.SUB_PROBLEM]
    root_edges = [edge for edge in suggestion.graph.edges if edge.source == root.id]

    assert suggestion.provider_result.provider == "stub"
    assert len(sub_problems) >= 3
    assert len(root_edges) >= 3
    assert suggestion.graph.metadata.validation.complete_branch_count >= 3
    assert any("stockout" in (node.content or "").lower() for node in sub_problems)
