________________________________________
Sentinel API
Sentinel API is a production-hardened service shell for running critical backend workloads safely.
It is not a product.
It is not a platform.
It is not “AI”.
It is the operational chassis around things that actually matter: models, rules engines, decision systems, or any service that must stay observable, interruptible, and boring under pressure.
________________________________________
What this is
Sentinel API provides:
•	A FastAPI service with predictable behavior under load
•	Structured JSON logging (machine-parseable, ops-friendly)
•	Prometheus metrics for latency, throughput, and prediction rate
•	Graceful shutdown and request draining
•	Kubernetes-native health endpoints (/live, /ready, /prestop)
•	Optional integrations for:
o	PostgreSQL (via SQLAlchemy)
o	Redis
o	Sentry
o	OpenTelemetry
•	A reference /predict endpoint to demonstrate safe request handling
Think of this as:
The gauges, kill-switches, and warning lights — not the engine.
________________________________________
What this is not
Sentinel API intentionally does not include:
•	UI dashboards
•	Data ontologies
•	Workflow builders
•	User management
•	Model training
•	Feature stores
•	Opinionated business logic
•	Vendor lock-in patterns
If you’re looking for a full-stack data platform, this is the wrong repo.
If you need a reliable execution surface that doesn’t lie to you when things go sideways — this is the right shape.
________________________________________
Why this exists
Most backend services fail in boring ways:
•	They hang during deploys
•	They lie about readiness
•	They drop requests silently
•	They can’t be stopped safely
•	They emit logs humans can’t parse
•	They only work when everything else is healthy
Sentinel exists to solve those problems first.
The assumption is simple:
Your logic will change. Your infrastructure must not.
________________________________________
Architecture (mental model)
┌────────────┐
│   Client   │
└─────┬──────┘
      │
      ▼
┌───────────────┐
│   Middleware  │  ← request IDs, metrics, logging, draining
└─────┬─────────┘
      │
      ▼
┌───────────────┐
│   Endpoints   │  ← /live /ready /predict /metrics
└─────┬─────────┘
      │
      ▼
┌───────────────┐
│   App State   │  ← readiness, shutdown, rate tracking
└─────┬─────────┘
      │
      ▼
┌───────────────┐
│ Dependencies  │  ← DB / Redis (optional, health-checked)
└───────────────┘
Everything above the business logic exists to keep the business logic honest.
________________________________________
Repo structure
app/
├── main.py          # App wiring + routes
├── config.py        # Environment-driven configuration
├── logging.py       # Structured JSON logging
├── metrics.py       # Prometheus metrics definitions
├── middleware.py    # Request lifecycle instrumentation
├── state.py         # Shared app state + rate tracking
├── lifespan.py      # Startup / shutdown logic
├── deps.py          # Dependency health checks
└── integrations.py  # Optional Sentry / OpenTelemetry setup
Each module has one job.
Nothing is “magical”.
Everything can be read top to bottom.
________________________________________
Health & lifecycle endpoints
/live
Basic liveness probe.
•	Returns 200 if the process is running
•	Does not check dependencies
/ready
Readiness probe.
•	Returns 503 if:
o	The service is draining
o	DB or Redis health checks fail
•	Designed for Kubernetes readiness gates
/prestop
Explicit drain trigger.
•	Marks the service as not-ready
•	Delays exit to allow load balancers to react
•	Useful for Kubernetes preStop hooks
________________________________________
Metrics
Exposed at /metrics (Prometheus format).
Tracked:
•	Request count (by method, path, status)
•	Request latency
•	Predictions per second (per pod)
•	Total predictions
Metrics access can be protected via METRICS_TOKEN.
________________________________________
Logging
All logs are emitted as structured JSON.
Example:
{
  "ts": "2025-01-01T12:00:00Z",
  "level": "INFO",
  "msg": "request",
  "pod_id": "api-7c9d",
  "env": "production",
  "path": "/predict",
  "method": "POST",
  "status_code": 200,
  "duration_ms": 23
}
This is intentional:
•	Logs are for machines first
•	Humans get clarity by querying, not scrolling
________________________________________
Configuration (environment variables)
Variable	Purpose
ENVIRONMENT	Environment name (development, production, etc.)
POD_ID	Instance identifier
DATABASE_URL	Optional PostgreSQL connection
REDIS_URL	Optional Redis connection
SENTRY_DSN	Optional Sentry integration
METRICS_TOKEN	Optional bearer token for /metrics
Unset variables simply disable features. No crashes.
________________________________________
Running locally
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
Visit:
•	http://localhost:8000/live
•	http://localhost:8000/ready
•	http://localhost:8000/metrics
________________________________________
How to extend this safely
Good additions:
•	Real model inference behind /predict
•	Auth middleware
•	Rate limiting
•	Background workers
•	Queue consumers
•	Explicit human-in-the-loop gates
Bad additions:
•	UI dashboards
•	Hidden global state
•	Implicit retries that hide failure
•	“Smart” abstractions without escape hatches
Rule of thumb:
If it makes failure harder to see or stop, it doesn’t belong here.
________________________________________
Design philosophy (explicit)
•	Observability beats cleverness
•	Human operators stay in control
•	Failure should be loud and legible
•	Graceful shutdown is not optional
•	Infrastructure should never lie
This repo is meant to be boring in the best way.
________________________________________
License / usage
Use it.
Fork it.
Strip it for parts.
Deploy it internally.
Do not turn it into a religion.
If it disappears tomorrow, you should still understand every line.
________________________________________
