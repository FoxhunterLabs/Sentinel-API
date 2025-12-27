from dataclasses import dataclass
from typing import Optional
import os


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
