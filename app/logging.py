import json
import logging
import time
from .config import SETTINGS


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


def configure_logging():
    logging.basicConfig(level=logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.getLogger().handlers = [handler]
    return logging.getLogger("sentinel.api")
