from fastapi import FastAPI

from .config import SETTINGS

# Optional imports
try:
    import sentry_sdk
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
except Exception:
    sentry_sdk = None
    SentryAsgiMiddleware = None

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except Exception:
    FastAPIInstrumentor = None


def setup_integrations(app: FastAPI, log):
    if SETTINGS.sentry_dsn and sentry_sdk:
        log.info("enabling sentry")
        sentry_sdk.init(dsn=SETTINGS.sentry_dsn)
        app.add_middleware(SentryAsgiMiddleware)

    if FastAPIInstrumentor:
        log.info("enabling opentelemetry")
        FastAPIInstrumentor.instrument_app(app)
