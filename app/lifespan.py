import asyncio
import time

import httpx

from .config import SETTINGS
from .state import state, rate_loop

# Optional deps
try:
    import sqlalchemy as sa
except Exception:
    sa = None

try:
    import redis.asyncio as redis
except Exception:
    redis = None


async def on_startup(log):
    log.info("startup")

    state.http = httpx.AsyncClient(timeout=SETTINGS.dep_timeout)

    if SETTINGS.database_url and sa:
        state.db_engine = sa.create_engine(
            SETTINGS.database_url,
            pool_pre_ping=True,
        )

    if SETTINGS.redis_url and redis:
        state.redis = redis.from_url(SETTINGS.redis_url)

    state._rate_task = asyncio.create_task(rate_loop())


async def on_shutdown(log):
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
