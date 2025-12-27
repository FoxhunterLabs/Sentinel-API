from __future__ import annotations

import asyncio
import signal
import time
import uuid
from typing import Any, Dict

import httpx
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import SETTINGS
from .logging import configure_logging
from .metrics import REQUEST_COUNT, REQUEST_LATENCY
from .state import state, rate_loop

# Optional integrations
try:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
except Exception:
    sentry_sdk = None
    SentryAsgiMiddleware = None

try:
    import sqlalchemy as sa
    from sqlalchemy import text
except Exception:
    sa = None
    text = None

try:
    import redis.asyncio as redis
except Exception:
    redis = None

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except Exception:
    FastAPIInstrumentor = None


log = configure_logging()

# -------------------------
# Lifespan
# -------------------------

async def on_startup():
    log.info("startup")
    state.http = httpx.AsyncClient(timeout=SETTINGS.dep_timeout)

    if SETTINGS.database_url and sa:
        state.db_engine = sa.create_engine(
            SETTINGS.database_url, pool_pre_ping=True
        )

    if SETTINGS.redis_url and redis:
        state.redis = redis.from_url(SETTINGS.redis_url)

    state._rate_task = asyncio.create_task(rate_loop())


async def on_shutdown():
    log.info("shutdown: waiting for active requests")
    deadline = time.time() + SETTINGS.shutdown_grace_seconds

    while state.active_requests > 0 and time.time() < deadline:
        await asyncio.sleep(0.1)

    if state._rate_task:
        state._rate_task.cancel()

    if state.http:
        await state.http.aclose()
    if state.redis:
        await state.redis.close()
    if state.db_engine:
        state.db_engine.dispose()


async def lifespan(app: FastAPI):
    await on_startup()
    yield
    await on_shutdown()


# -------------------------
# App
# -------------------------

app = FastAPI(
    title="Sentinel API",
    version="0.1.0",
    lifespan=lifespan,
)

if SETTINGS.sentry_dsn and sentry_sdk:
    sentry_sdk.init(dsn=SETTINGS.sentry_dsn)
    app.add_middleware(SentryAsgiMiddleware)

if FastAPIInstrumentor:
    FastAPIInstrumentor.instrument_app(app)


# -------------------------
# Middleware
# -------------------------

@app.middleware("http")
async def metrics_and_drain(request: Request, call_next):
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


# -------------------------
# Health
# -------------------------

async def check_db():
    if not state.db_engine:
        return True

    def _ping():
        with state.db_engine.connect() as c:
            c.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_ping),
            SETTINGS.dep_timeout,
        )
        return True
    except Exception:
        return False


async def check_redis():
    if not state.redis:
        return True

    try:
        await asyncio.wait_for(
            state.redis.ping(),
            SETTINGS.dep_timeout,
        )
        return True
    except Exception:
        return False


@app.get("/live")
async def live():
    return {"live": True}


@app.get("/ready")
async def ready(response: Response):
    if not state.ready:
        response.status_code = 503
        return {"ready": False}

    ok = await check_db() and await check_redis()
    if not ok:
        response.status_code = 503
    return {"ready": ok}


@app.get("/prestop")
async def prestop():
    state.ready = False
    log.warning("preStop: draining")
    await asyncio.sleep(8)
    return {"ok": True}


# -------------------------
# Metrics
# -------------------------

security = HTTPBearer(auto_error=False)

@app.get("/metrics")
async def metrics(
    creds: HTTPAuthorizationCredentials = Depends(security),
):
    if SETTINGS.metrics_token:
        if not creds or creds.credentials != SETTINGS.metrics_token:
            raise HTTPException(status_code=403)

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# -------------------------
# Prediction
# -------------------------

@app.post("/predict")
async def predict(payload: Dict[str, Any]):
    await asyncio.sleep(0.02)
    state.record_prediction()
    return {"score": 0.42}


# -------------------------
# Signals
# -------------------------

def handle_signal(sig, _):
    log.warning(f"signal {sig}: marking not-ready")
    state.ready = False
    state.shutting_down = True


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

