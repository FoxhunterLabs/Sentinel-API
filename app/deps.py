import asyncio

from .config import SETTINGS
from .state import state

try:
    from sqlalchemy import text
except Exception:
    text = None


async def check_db():
    if not state.db_engine or not text:
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
