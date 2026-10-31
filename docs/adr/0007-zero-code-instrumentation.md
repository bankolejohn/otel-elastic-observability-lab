# ADR-0007: Zero-code OTel instrumentation over manual SDK setup

Date: 2026-10-28
Status: Accepted

## Context

OpenTelemetry Python supports two ways to get a service instrumented:

1. **Zero-code / automatic**: install `opentelemetry-distro` plus the
   relevant `opentelemetry-instrumentation-*` packages for the libraries
   you use, then run the process via the `opentelemetry-instrument` CLI
   wrapper. It monkey-patches the target libraries (FastAPI, httpx,
   SQLAlchemy, Redis, stdlib `logging`) at interpreter startup, before
   application code is imported. No application code changes needed for
   the automatic part.
2. **Manual / code-based**: call `TracerProvider()`, `MeterProvider()`,
   `LoggerProvider()`, configure exporters and processors yourself in
   application code, and instrument each library explicitly.

Each service also needs *some* hand-written spans/metrics beyond what
auto-instrumentation gives you "for free" at HTTP/DB/cache boundaries —
auto-instrumentation can't know that `get_product_cached()` or
`reserve_stock()` are meaningful units of business logic worth their own
span.

## Decision

Use zero-code instrumentation (`opentelemetry-instrument uvicorn ...`,
configured via `OTEL_*` environment variables in `docker-compose.yml`) as
the baseline for every service, and add a small number of hand-written
spans/metrics on top of it using `trace.get_tracer(...)` /
`metrics.get_meter(...)` for the specific business-logic steps worth
seeing on their own (see `get_product_cached` in orders-service,
`reserve_stock` in inventory-service).

## Alternatives considered

- **Fully manual SDK setup in every service** (configuring
  `TracerProvider`/exporters/processors by hand in each `main.py`). This is
  the more "from first principles" way to learn what the SDK is actually
  doing, and is worth doing as a dedicated exercise eventually. Rejected as
  the *baseline* for this stage because it means writing near-identical
  20+ lines of SDK bootstrap code in three services before any actual
  tracing happens, which is exactly the kind of incidental complexity
  Stage A tried to avoid (see ADR-0002). Zero-code gets a working,
  observable system faster, and is also genuinely how most real
  organizations instrument existing services (bolt on tracing without
  touching the application).
- **Only zero-code, no manual spans at all.** Would show HTTP/DB/cache
  boundaries but nothing about what happens inside a service between
  those boundaries — insufficient for the later chaos-diagnosis stage,
  where "which step inside orders-service took the time" matters.

## Consequences

- Instrumentation is controlled entirely through environment variables
  (see the `x-otel-env` anchor in `docker-compose.yml`), which keeps
  Dockerfiles generic and makes the Stage C/D change (console → OTLP
  exporters) a config-only change, not a code change.
- The two logging.basicConfig() calls already in each service's `main.py`
  become documented no-ops when run under `opentelemetry-instrument` with
  `OTEL_PYTHON_LOG_CORRELATION=true` (that instrumentation calls
  `logging.basicConfig()` first, during interpreter startup, and Python's
  `logging` module only honors the first call). This is intentional and
  commented in the code, but it is a real sharp edge: if you ever see log
  lines *without* `trace_id=...` in them, suspect that this environment
  variable isn't reaching the container, not that the code is broken.
- Hand-written spans sit inside automatically-created ones (visible via
  `parent_id` in the console output), so the two approaches compose rather
  than conflict.

## Revisit when

If a future stage wants to teach SDK internals directly (sampling
strategies, custom span processors, batching behavior), do that as a
focused, separate exercise rather than replacing the zero-code baseline.
