"""Feature flag defaults.

Phase 1 keeps flags in-memory: defaults here are the source of truth, and
admins can override them for the running process via
``POST /api/v1/admin/feature-flags``. Phase 2 will back this with a
persistent store so overrides survive restarts.

Flag values are plain booleans to keep the surface narrow. Add a new key
here only after it has a corresponding guard in the code that consumes it
— an unused flag is dead weight.
"""

from __future__ import annotations

DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    # Whether the new library-based export engine is reachable.
    # When false, /export/jobs POST returns 503 even if the engine is wired.
    "export_engine_enabled": False,
    # Enables calling web-enrichment during ingest. Disabled by default
    # until rate-limited providers are configured.
    "web_enrichment_enabled": False,
    # Exposes Phase 2 admin dashboards. Until then they return placeholder
    # payloads so the UI can be iterated independently.
    "admin_dashboard_enabled": True,
    # Toggles the WebSocket ingest-progress channel. Off until the worker
    # publishes events.
    "ingest_progress_ws_enabled": False,
}
