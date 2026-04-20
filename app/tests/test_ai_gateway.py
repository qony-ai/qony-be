from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.enums import NodeType
from app.services.ai_router import get_ai_router
from app.services.ai_service import AIService


def test_ai_router_selects_stub():
    settings = Settings(database_url="sqlite:///./factory-test.db", ai_provider="stub")
    router = get_ai_router(settings)
    assert router.provider == "stub"


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


def test_stub_ingest_produces_flat_typed_graph(app, test_settings):
    raw_text = """
    BUSINESS CASE
    Implementasi Sistem Inventory & Procurement Digital
    Inti rekomendasi: lanjutkan implementasi bertahap untuk memperbaiki kontrol stok dan pembelian.

    1. Latar belakang & masalah
    Saat ini proses monitoring stok dan approval pembelian masih mengandalkan spreadsheet terpisah.
    - Stockout pada item fast-moving menyebabkan lost sales dan mengganggu service level.
    - Pembelian darurat meningkatkan biaya dan membuat vendor planning tidak stabil.

    2. Rekomendasi
    Rollout sistem inventory digital dalam 2 fase untuk menurunkan stockout rate sebesar 40%.
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

    graph = suggestion.graph
    node_types = {node.type for node in graph.nodes}

    assert suggestion.provider_result.provider == "stub"
    assert graph.metadata.validation.is_valid is True
    assert any(node.type == NodeType.PROBLEM for node in graph.nodes), (
        "Deterministic stub must produce at least one PROBLEM node from a business case document."
    )
    assert graph.edges, "Deterministic stub must connect the root problem to its supporting nodes."
    assert NodeType.SOLUTION in node_types or NodeType.EVIDENCE in node_types, (
        "Business case with a recommendation should produce a SOLUTION or EVIDENCE node."
    )
