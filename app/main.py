from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# -------------------------
# Optional integrations
# -------------------------

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


# -------------------------
# Config
# -------------------------

@dataclass(frozen=True)
class Settings:
    environment: str
    pod_id: str
    database_url: Optional[str]
    redis_url: Optional[str]
    mlflow_tracking_uri: Optional[str]
    sentry_dsn: Optional[str]
    metrics_token: Optional[str]

    dep_timeout: float = 1.5
    shutdown_grace_seconds: float = 40.0


def load_settings() -> Settings:
    return Settings(
        environment=os.getenv("ENVIRONMENT", "development"),
        pod_id=os.getenv("POD_ID", "unknown"),
        database_url=os.getenv("DATABASE_URL"),
        redis_url=os.getenv("REDIS_URL"),
        mlflow_tracking_uri=os.getenv("MLFLOW_TRACKING_URI"),
        sentry_dsn=os.getenv("SENTRY_DSN"),
        metrics_token=os.getenv("METRICS_TOKEN"),
    )


SETTINGS = load_settings()


# -------------------------
# Logging
# -------------------------

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "msg": record.getMessage(),
            "pod_id": SETTINGS.pod_id,
            "env": SETTINGS.environment,
        }
        for k in (
            "request_id",
            "path",
            "method",
            "status_code",
            "duration_ms",
        ):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload)


logging.basicConfig(level=logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.getLogger().handlers = [handler]
log = logging.getLogger("bi.api")


# -------------------------
# Metrics
# -------------------------

REQUEST_COUNT = Counter(
    "http_requests_total", "HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "Latency", ["method", "path"]
)
PREDICTIONS_PER_SECOND = Gauge(
    "predictions_per_second", "Predictions/sec (per pod)"
)
PREDICTIONS_TOTAL = Counter("predictions_total", "Total predictions")


# -------------------------
# App state
# -------------------------

class AppState:
    def __init__(self):
        self.ready = True
        self.shutting_down = False
        self.active_requests = 0

        self.http: Optional[httpx.AsyncClient] = None
        self.db_engine = None
        self.redis = None

        self._rate_window = 0
        self._rate_ts = time.monotonic()
        self._rate_task: Optional[asyncio.Task] = None


state = AppState()


# -------------------------
# Lifespan (startup + drain)
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
# FastAPI app
# -------------------------

app = FastAPI(
    title="Business Intelligence API",
    version="3.0",
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
        request.method, request.url.path, response.status_code
    ).inc()
    REQUEST_LATENCY.labels(
        request.method, request.url.path
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
# Dependency checks (with retry)
# -------------------------

async def check_db():
    if not state.db_engine:
        return True, "db:disabled"

    for i in range(3):
        try:
            def _ping():
                with state.db_engine.connect() as c:
                    c.execute(text("SELECT 1"))

            await asyncio.wait_for(
                asyncio.to_thread(_ping), SETTINGS.dep_timeout
            )
            return True, "db:ok"
        except Exception:
            if i == 2:
                return False, "db:fail"
            await asyncio.sleep(0.3)


async def check_redis():
    if not state.redis:
        return True, "redis:disabled"

    for i in range(3):
        try:
            await asyncio.wait_for(
                state.redis.ping(), SETTINGS.dep_timeout
            )
            return True, "redis:ok"
        except Exception:
            if i == 2:
                return False, "redis:fail"
            await asyncio.sleep(0.3)


# -------------------------
# Health endpoints
# -------------------------

@app.get("/live")
async def live():
    return {"live": True}


@app.get("/ready")
async def ready(response: Response):
    if not state.ready:
        response.status_code = 503
        return {"ready": False, "reason": "draining"}

    db_ok, _ = await check_db()
    r_ok, _ = await check_redis()

    ok = db_ok and r_ok
    if not ok:
        response.status_code = 503
    return {"ready": ok}


@app.get("/prestop")
async def prestop():
    state.ready = False
    log.warning("preStop: draining")
    await asyncio.sleep(8.0)
    return {"ok": True, "draining": True, "delay_applied": True}


# -------------------------
# Metrics (auth protected)
# -------------------------

security = HTTPBearer(auto_error=False)

@app.get("/metrics")
async def metrics(
    creds: HTTPAuthorizationCredentials = Depends(security),
):
    if SETTINGS.metrics_token:
        if not creds or creds.credentials != SETTINGS.metrics_token:
            raise HTTPException(status_code=403, detail="Forbidden")

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# -------------------------
# Prediction example
# -------------------------

def record_prediction(n=1):
    state._rate_window += n
    PREDICTIONS_TOTAL.inc(n)


async def rate_loop():
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        rate = state._rate_window / max(now - state._rate_ts, 1e-6)
        PREDICTIONS_PER_SECOND.set(rate)
        state._rate_window = 0
        state._rate_ts = now


@app.post("/predict")
async def predict(payload: Dict[str, Any]):
    await asyncio.sleep(0.02)
    record_prediction()
    return {"score": 0.42}


# -------------------------
# Signal handling
# -------------------------

def handle_signal(sig, _):
    log.warning(f"signal {sig}: marking not-ready")
    state.ready = False
    state.shutting_down = True


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)
