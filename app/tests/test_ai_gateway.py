from app.core.config import Settings
from app.integrations.ai.factory import build_ai_adapter
from app.services.ai_router import AIRouter


def test_ai_provider_factory_selects_stub():
    settings = Settings(_env_file=None, database_url="sqlite:///./factory-test.db", ai_provider="stub")
    provider = build_ai_adapter(settings)
    assert provider.provider == "stub"


def test_ai_router_selects_operation_specific_ollama_model():
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///./router-test.db",
        ai_mode="local",
        ollama_model="fallback-model",
        ollama_model_extraction="extract-model",
        ollama_model_generation="generate-model",
        ollama_model_scraping="scrape-model",
    )

    router = AIRouter(settings)

    assert router.model_for_use_case(use_case="extraction") == "extract-model"
    assert router.model_for_use_case(use_case="generation") == "generate-model"
    assert router.model_for_use_case(use_case="scraping") == "scrape-model"
