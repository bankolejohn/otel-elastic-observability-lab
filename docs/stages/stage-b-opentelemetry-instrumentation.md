# Stage B — Instrument every service with OpenTelemetry

Status: **Complete**
Related ADRs: [0007](../adr/0007-zero-code-instrumentation.md)

## What

Every service (`api-gateway`, `orders-service`, `inventory-service`) now
emits traces, metrics, and logs via OpenTelemetry, printed to each
container's console (`stdout`) for now — no Collector, no external backend
yet. Concretely:

- **Automatic (zero-code) instrumentation** of FastAPI (inbound HTTP),
  httpx (outbound HTTP), SQLAlchemy (DB queries + connection pool stats),
  and Redis — zero application code changes, just installed packages +
  running the process under `opentelemetry-instrument`.
- **Manual spans** around two specific business-logic steps:
  `get_product_cached` in orders-service, `reserve_stock` in
  inventory-service — each with custom attributes (`cache.hit`,
  `inventory.result`, etc.).
- **Manual metrics**: two business counters, `orders.created` and
  `orders.cache_lookup` (labeled by hit/miss).
- **Log-trace correlation**: every log line any service already printed
  now also carries `trace_id=... span_id=...`, with no changes to the
  logging calls themselves.

## Why

Stage A gave us a system with real network hops but no way to see what
happens when a request crosses them, other than reading unrelated log
lines from three separate `docker compose logs` streams and mentally
stitching them together. Stage B's only job is to make the *connections*
between those hops visible — a trace — and to make a stray log line
traceable back to the request that caused it.

Console exporters (not OTLP, not a Collector yet) are deliberate: this
stage is about understanding what a span/trace/log-with-trace-context
actually *is*, structurally, before adding infrastructure to move it
anywhere. Stage C adds the Collector; the only change at that point should
be swapping exporters, not relearning what's being exported.

## How it works

### Zero-code instrumentation

Each service's `requirements.txt` gained `opentelemetry-distro` plus the
`opentelemetry-instrumentation-*` packages matching the libraries it
actually uses (FastAPI everywhere; httpx in api-gateway and
orders-service; SQLAlchemy in orders-service and inventory-service; Redis
in orders-service only). Each Dockerfile's `CMD` changed from

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

to

```dockerfile
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`opentelemetry-instrument` is a wrapper that, before `app.main` is even
imported, patches the installed libraries it has matching instrumentation
packages for. No line in `app/main.py` had to change for this part.

### Configuration

All OTel configuration lives in `docker-compose.yml`, as environment
variables, shared across services via a YAML anchor:

```yaml
x-otel-env: &otel-env
  OTEL_TRACES_EXPORTER: console
  OTEL_METRICS_EXPORTER: console
  OTEL_LOGS_EXPORTER: console
  OTEL_PYTHON_LOG_CORRELATION: "true"
  OTEL_METRIC_EXPORT_INTERVAL: "10000"
  OTEL_RESOURCE_ATTRIBUTES: "service.namespace=obs-demo-shop,deployment.environment=local"
```

merged into each service with `<<: *otel-env`, plus a per-service
`OTEL_SERVICE_NAME`. Centralizing this means Stage C/D only has to edit
these few lines (swap `console` for `otlp`, point at the Collector) rather
than touching every service block.

### Manual spans and metrics

`orders-service/app/main.py` and `inventory-service/app/main.py` each
acquire a tracer (`trace.get_tracer(...)`) and, in orders-service, a
meter (`metrics.get_meter(...)`) at module level, then use
`tracer.start_as_current_span("name")` as a context manager around the
specific step worth seeing on its own. Spans created this way automatically
nest under whatever span is "current" at the time — in our case, the
automatic FastAPI server span — with no manual parent-wiring needed.

### Log correlation, and the basicConfig() gotcha

Each service already called `logging.basicConfig(...)` to set a log
format. `opentelemetry-instrumentation-logging`, when
`OTEL_PYTHON_LOG_CORRELATION=true`, also calls `logging.basicConfig(...)`
— with its own format string containing `trace_id`/`span_id` placeholders
— during interpreter startup, **before** `app/main.py` is imported.
Python's `logging.basicConfig()` only honors the *first* call in a
process; every later call is silently ignored. So our own `basicConfig()`
call in `main.py` is a documented no-op under `opentelemetry-instrument`,
and only matters as a fallback if the service is ever run directly via
plain `uvicorn` (no OTel wrapping) — it still sets up sane logging in that
case, just without trace context. This is called out in a code comment at
each `basicConfig()` call site, and in ADR-0007.

## How to verify

```bash
docker compose up --build

# place an order
curl -s -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 2, "quantity": 1}'

sleep 5   # give the batch span processor / metric reader a moment to flush

# 1. Find a trace_id in orders-service's logs
docker compose logs orders-service --no-color | grep "trace_id="

# 2. Confirm the SAME trace_id shows up in inventory-service's logs
#    (proves trace context propagated across the network boundary)
docker compose logs inventory-service --no-color | grep "<trace_id from step 1>"

# 3. Confirm it shows up in api-gateway's logs too (all 3 hops, one trace)
docker compose logs api-gateway --no-color | grep "<trace_id from step 1>"

# 4. Find the manual spans
docker compose logs orders-service --no-color | grep -A 15 '"name": "get_product_cached"'
docker compose logs inventory-service --no-color | grep -A 15 '"name": "reserve_stock"'

# 5. Find the custom business metrics
docker compose logs orders-service --no-color | grep -A 10 '"name": "orders.created"'
docker compose logs orders-service --no-color | grep -A 10 '"name": "orders.cache_lookup"'
```

**Actually run on 2026-10-28**, placing one order for product 2: all three
services' logs shared `trace_id=77457be0dfecd20702cbadf7bd9b0397`. Example
correlated log lines from orders-service:

```
2026-10-28 14:54:34,359 INFO [orders-service] [main.py:77] [trace_id=77457be0dfecd20702cbadf7bd9b0397 span_id=7fefafc954f054e1 resource.service.name=orders-service trace_sampled=True] - Cache miss for product 2, calling inventory-service
2026-10-28 14:54:34,692 INFO [httpx] [_client.py:1038] [trace_id=77457be0dfecd20702cbadf7bd9b0397 span_id=bf8c8fd7c4066870 resource.service.name=orders-service trace_sampled=True] - HTTP Request: POST http://inventory-service:8000/products/2/reserve "HTTP/1.1 200 OK"
```

The matching span from inventory-service, showing the manual `reserve_stock`
span nested under the automatic FastAPI server span (`parent_id`), with our
custom attributes attached:

```json
{
    "name": "reserve_stock",
    "context": {
        "trace_id": "0x77457be0dfecd20702cbadf7bd9b0397",
        "span_id": "0x1a876a8e60b25532"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": "0x338d6eac761c194f",
    "attributes": {
        "inventory.product_id": 2,
        "inventory.quantity_requested": 1,
        "inventory.result": "reserved",
        "inventory.remaining_stock": 29
    }
}
```

And the auto-instrumentation gave us things we didn't ask for, for free —
e.g. SQLAlchemy's connection-pool gauges, directly validating ADR-0004's
premise that the pool is small and watchable:

```json
{
    "name": "db.client.connections.usage",
    "data": {"data_points": [
        {"attributes": {"state": "idle"}, "value": 1},
        {"attributes": {"state": "used"}, "value": 0}
    ]}
}
```

All five checks passed as described.

## Troubleshooting log

**Console output is batched, not instant.** Spans/metrics don't print the
moment a request finishes — the SDK's default batch span processor and
the 10s metric export interval mean there's a short delay, and output for
one request can interleave with output from the next if you're making
requests quickly. When verifying by hand, add a short `sleep` after the
request before grepping logs, as in the commands above.

**Rebuilds are slower now.** Adding the OTel packages meaningfully
increases `pip install` time (observed 80-90s for orders-service alone,
up from roughly 90s total across all three services in Stage A) because
pip's dependency resolver has more packages to reconcile. Not a problem,
just don't assume a stalled-looking build output is actually stuck —
compare against the timestamps in the build log before interrupting it.

## What's next

Stage C runs an OpenTelemetry Collector in its own container, and points
every service's `OTEL_*_EXPORTER` at it instead of `console` — the
receiver/processor/exporter pipeline concept, and the first time telemetry
leaves the process that generated it.
