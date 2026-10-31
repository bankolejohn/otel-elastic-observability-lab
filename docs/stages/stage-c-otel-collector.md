# Stage C — Run an OpenTelemetry Collector locally

Status: **Complete**
Related ADRs: [0008](../adr/0008-collector-design.md)

## What

A fourth container, `otel-collector`, now sits between every app service
and "wherever telemetry goes." Every service's `OTEL_*_EXPORTER` changed
from `console` to `otlp`, pointed at the Collector over gRPC. The
Collector's only job right now is to receive that OTLP data and print it
to its own console via a `debug` exporter — but the pipeline shape
(`receiver → processors → exporter`) is exactly what Stage D extends.

## Why

Stage B proved traces/logs/metrics worked, but left them scattered across
three separate `docker compose logs <service>` streams — to see one
request's full story you had to know to grep three different places for
the same `trace_id`. That's exactly the problem the Collector exists to
solve: **one telemetry sink shared by multiple services**. Stage C's job
is to make that collapse from "three places" to "one place" visible,
before Stage D changes what that one place is (from the Collector's own
console to Elasticsearch).

Routing every service through a Collector now, rather than pointing them
directly at Elastic Cloud in Stage D, also means the *application-side*
configuration never has to change again — only `otel-collector/config.yaml`
does. That's not a hypothetical benefit: compare `docker-compose.yml`'s
`x-otel-env` block before and after this stage. Stage B→C changed every
line in it. Stage C→D should change none of it.

## How it works

### The Collector container

```yaml
otel-collector:
  image: otel/opentelemetry-collector-contrib:0.153.0
  command: ["--config=/etc/otel-collector-config.yaml"]
  volumes:
    - ./otel-collector/config.yaml:/etc/otel-collector-config.yaml:ro
  ports:
    - "4317:4317"   # OTLP gRPC
    - "4318:4318"   # OTLP HTTP
```

### The pipeline config (`otel-collector/config.yaml`)

```
otlp (receiver, :4317 grpc / :4318 http)
  -> memory_limiter (processor)
  -> batch (processor)
  -> debug (exporter)
```

for all three signals (traces, metrics, logs) — see ADR-0008 for why
`memory_limiter`+`batch` and why the contrib image/pinned version/`debug`
exporter specifically.

### Pointing the apps at it

Only `docker-compose.yml`'s shared `x-otel-env` block changed — no app
code, no Dockerfile:

```yaml
x-otel-env: &otel-env
  OTEL_TRACES_EXPORTER: otlp
  OTEL_METRICS_EXPORTER: otlp
  OTEL_LOGS_EXPORTER: otlp
  OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
  OTEL_EXPORTER_OTLP_PROTOCOL: grpc
  ...
```

Each service's `requirements.txt` also gained `opentelemetry-exporter-otlp`
(Stage B only had the built-in console exporter available; sending OTLP
needs this package installed).

### What actually changes in what you see

Each service's own `docker compose logs <service>` output goes back to
being quiet — just uvicorn access logs and the app's own
`logger.info(...)` lines (still carrying `trace_id=...`, since that's a
log-formatting change, independent of where the *exported copy* of the
log goes). The raw span/metric JSON dumps from Stage B are gone from the
app containers and now only appear in `docker compose logs otel-collector`.

## How to verify

```bash
docker compose up --build

curl -s -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 1}'

sleep 10   # batch processor + metric export interval

# 1. The service's own logs should be quiet now -- just app log lines,
#    no raw span/metric JSON (compare to Stage B's verification output)
docker compose logs orders-service --no-color --tail 10

# 2. Grab the trace_id from one of those lines, then confirm it shows up
#    in the Collector's console, with spans from ALL THREE services
docker compose logs otel-collector --no-color | grep -c "<trace_id>"
docker compose logs otel-collector --no-color | grep "service.name:" | sort | uniq -c
```

**Actually run on 2026-10-29:** placed an order for product 1, got
`trace_id=735cea404f035b0e8c969e2ef9ce1d8a`. `orders-service`'s own log
output was back to plain app log lines only (confirmed no stray span/
metric JSON). The same trace_id appeared **64 times** in the Collector's
console output, and `service.name` values present were
`api-gateway` (8), `inventory-service` (9), and `orders-service` (10) —
all three services' telemetry, for one request, in one place. Spotted a
span we didn't know to expect from reading the code alone: the Redis
instrumentation produced its own client span (`Name: GET`, under
`InstrumentationScope opentelemetry.instrumentation.redis`), nested under
our manual `get_product_cached` span — a reminder that auto-instrumentation
surfaces real detail, not just the boundaries you already knew about.

Checked for OTLP export errors in each service's logs during container
startup (before the Collector was necessarily listening yet) — found
none, consistent with OTLP exporters' documented retry/backoff behavior,
though actually forcing the Collector down and watching the result is
deferred to Stage G (chaos), not tested here.

## Troubleshooting log

No failures this stage — build took noticeably longer than Stage B
(roughly 3-4 minutes more across the three services) because
`opentelemetry-exporter-otlp` pulls in `grpcio`, which is a larger
package. Nothing to fix, just slower; confirmed via the Docker build log
timestamps before assuming anything was stuck.

## What's next

Stage D creates an Elastic Cloud trial deployment and adds an
`elasticsearch` exporter to `otel-collector/config.yaml`, replacing (or
sitting alongside, while verifying) the `debug` exporter — the first time
telemetry leaves `docker compose` entirely.
