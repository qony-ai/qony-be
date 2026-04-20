"""Usage limits per plan tier.

Applied by :mod:`app.services.usage_service` at request time. Values are
intentionally conservative in Phase 1 — Phase 2 will reconcile them with
the Midtrans billing catalogue and move them behind feature flags.

Keys:

* ``ai_calls_per_month`` — counts any :class:`app.domain.enums.AIRequestOperation`
  event (ingest, workspace_mutation, export_assist).
* ``exports_per_month`` — counts completed :class:`app.models.export_job.ExportJob`.
* ``document_uploads_per_month`` — counts ingest job submissions.

Use :func:`get_limits` to resolve a tier name to its limit map so callers
don't couple to internal keys.
"""

from __future__ import annotations

from typing import Literal, TypedDict

PlanTier = Literal["free", "pro", "enterprise"]


class UsageLimits(TypedDict):
    ai_calls_per_month: int | None
    exports_per_month: int | None
    document_uploads_per_month: int | None


LIMITS: dict[PlanTier, UsageLimits] = {
    "free": {
        "ai_calls_per_month": 50,
        "exports_per_month": 3,
        "document_uploads_per_month": 10,
    },
    "pro": {
        "ai_calls_per_month": 1000,
        "exports_per_month": 50,
        "document_uploads_per_month": 200,
    },
    "enterprise": {
        "ai_calls_per_month": None,
        "exports_per_month": None,
        "document_uploads_per_month": None,
    },
}

DEFAULT_TIER: PlanTier = "free"


def get_limits(tier: PlanTier | str | None) -> UsageLimits:
    if tier in LIMITS:
        return LIMITS[tier]  # type: ignore[index]
    return LIMITS[DEFAULT_TIER]
