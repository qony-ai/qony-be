"""In-memory feature-flag service.

Phase 1 scope: backs admin overrides with a process-local dict seeded
from :data:`app.core.feature_flags.DEFAULT_FEATURE_FLAGS`. Phase 2 will
replace the storage layer with a table / KV store so overrides are
durable and shared across workers.

Because overrides are process-local today, they will not persist across
restarts and two backend replicas will diverge. The admin UI must warn
on this until the store is replaced.
"""

from __future__ import annotations

import threading
from copy import deepcopy

from app.core.exceptions import NotFoundError
from app.core.feature_flags import DEFAULT_FEATURE_FLAGS


class FeatureFlagsService:
    _lock = threading.Lock()
    _overrides: dict[str, bool] = {}

    def list_flags(self) -> dict[str, bool]:
        with self._lock:
            merged = deepcopy(DEFAULT_FEATURE_FLAGS)
            merged.update(self._overrides)
            return merged

    def get_flag(self, key: str) -> bool:
        flags = self.list_flags()
        if key not in flags:
            raise NotFoundError(f"Feature flag '{key}' is not defined.")
        return flags[key]

    def set_flag(self, key: str, value: bool) -> dict[str, bool]:
        if key not in DEFAULT_FEATURE_FLAGS:
            raise NotFoundError(f"Feature flag '{key}' is not defined.")
        with self._lock:
            self._overrides[key] = value
        return self.list_flags()

    def reset_flag(self, key: str) -> dict[str, bool]:
        if key not in DEFAULT_FEATURE_FLAGS:
            raise NotFoundError(f"Feature flag '{key}' is not defined.")
        with self._lock:
            self._overrides.pop(key, None)
        return self.list_flags()

    def reset_all(self) -> dict[str, bool]:
        with self._lock:
            self._overrides.clear()
        return self.list_flags()


feature_flags_service = FeatureFlagsService()
