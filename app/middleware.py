import time
import uuid
from fastapi import Request

from .metrics import REQUEST_COUNT, REQUEST_LATENCY
from .state import state


def metrics_and_drain_middleware(log):
    async def middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        start = time.perf_counter()

        state.active_requests += 1
        try:
            response = await call_next(request)
        finally:
            state.active_requests -= 1

        dur_ms = int((time.perf_counter() - start) * 1000)

        REQUEST_COUNT.labels(
            request.method,
            request.url.path,
            response.status_code,
        ).inc()

        REQUEST_LATENCY.labels(
            request.method,
            request.url.path,
        ).observe(dur_ms / 1000)

        log.info(
            "request",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": dur_ms,
            },
        )

        response.headers["x-request-id"] = request_id
        return response

    return middleware
