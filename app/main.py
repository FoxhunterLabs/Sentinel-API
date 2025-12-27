from __future__ import annotations

import asyncio
import signal
from typing import Any, Dict

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Response,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import SETTINGS
from .deps import check_db, check_redis
from .integrations import setup_integrations
from .lifespan import on_startup, on_shutdown
from .logging import configure_logging
from .middleware import metrics_and_drain_middleware
from .state import state


log = configure_logging()


async def lifespan(app: FastAPI):
    await on_startup(log)
    yield
    await on_shutdown(log)


app = FastAPI(
    title="Sentinel API",
    version="0.1.0",
    lifespan=lifespan,
)

app.middleware("http")(metrics_and_drain_middleware(log))
setup_integrations(app, log)

# -------------------------
# Health
# -------------------------

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
