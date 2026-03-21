from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request

from app.core.request_context import reset_request_id, set_request_id

logger = logging.getLogger("qony.request")


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        settings = request.app.state.settings
        request_id = request.headers.get(settings.request_id_header, str(uuid4()))
        request.state.request_id = request_id
        token = set_request_id(request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request.completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            reset_request_id(token)

        response.headers[settings.request_id_header] = request_id
        return response
