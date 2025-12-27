import asyncio
import time
from typing import Optional

import httpx

from .metrics import (
    PREDICTIONS_PER_SECOND,
    PREDICTIONS_TOTAL,
)


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

    def record_prediction(self, n: int = 1):
        self._rate_window += n
        PREDICTIONS_TOTAL.inc(n)


state = AppState()


async def rate_loop():
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        rate = state._rate_window / max(now - state._rate_ts, 1e-6)
        PREDICTIONS_PER_SECOND.set(rate)
        state._rate_window = 0
        state._rate_ts = now
