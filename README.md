# Observability & Monitoring Learning Pipeline

A hands-on project for learning observability from the ground up: instrument a
real app with OpenTelemetry, ship telemetry through a Collector into Elastic
Cloud, and practice diagnosing failures with traces, logs, and anomaly
detection.

## Roadmap

| Stage | Status | What it is | Docs |
|---|---|---|---|
| A | **Done** | Full-stack app running locally, no telemetry yet | [stage-a-foundation-app.md](docs/stages/stage-a-foundation-app.md) |
| B | **Done** | Instrument every service with OpenTelemetry (traces, metrics, logs) | [stage-b-opentelemetry-instrumentation.md](docs/stages/stage-b-opentelemetry-instrumentation.md) |
| C | **Done** | Run an OpenTelemetry Collector locally (Docker) | [stage-c-otel-collector.md](docs/stages/stage-c-otel-collector.md) |
| D | **Done** | Point the Collector at an Elastic Cloud trial | [stage-d-elastic-cloud.md](docs/stages/stage-d-elastic-cloud.md) |
| E | **Done** | Explore the data in Kibana (traces, service map, log↔trace correlation) | [stage-e-kibana-exploration.md](docs/stages/stage-e-kibana-exploration.md) |
| F | **Done** | Anomaly detection on our telemetry (custom ML job — the built-in APM toggle isn't reachable with our architecture, see ADR-0012) | [stage-f-anomaly-detection.md](docs/stages/stage-f-anomaly-detection.md) |
| G | **Done** | Inject chaos (slow responses, DB timeouts, dependency failures) and diagnose it using the pipeline | [stage-g-chaos-engineering.md](docs/stages/stage-g-chaos-engineering.md) |
| 2 | **Done** | Apply the Elastic Streams / ML pattern from the reference Medium article on top of this | [stage-2-elastic-streams.md](docs/stages/stage-2-elastic-streams.md) |

**The originally-scoped roadmap is complete.** Post-completion
extensions, picked up afterward:

| Stage | Status | What it is | Docs |
|---|---|---|---|
| H | **Done** | Fix the query_timeout/pool_exhausted timeout race (ADR-0018) + browser/RUM instrumentation | [stage-h-browser-instrumentation.md](docs/stages/stage-h-browser-instrumentation.md) |
| I | **Done** | Live-create the three alert rules via Kibana's API | [stage-i-alert-rules.md](docs/stages/stage-i-alert-rules.md) |
| J | Not started | Build a real Kibana dashboard | — |
| K | Ongoing | Let the ML jobs (`service_request_spikes`, `obs_shop_error_spikes`) mature with real history | — |

## Documentation map

This project is documented the way a real production system should be —
so that six months from now, re-reading it tells you what exists, why it's
built that way, and how to operate it, without having to reconstruct any
of that from memory or git log archaeology.

- **[`README.md`](README.md)** (this file) — entry point, roadmap, quick start.
- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — the system as it exists *right now*. Rewritten in place each stage. Read this to understand what's currently running.
- **[`docs/stages/`](docs/stages/)** — one doc per stage, written once that stage is done: what was built, why it was built before/after other things, how it works, exactly how to verify it, and what actually went wrong while building it. Read these to understand *how we got here*.
- **[`docs/adr/`](docs/adr/)** — Architecture Decision Records: the specific *why* behind each non-obvious choice (tech stack, deliberately undersized connection pools, etc.), alternatives considered, and trade-offs accepted. Read these when something in the code looks like a strange choice.
- **[`docs/glossary.md`](docs/glossary.md)** — concept definitions (span, trace, connection pool, reroute pipeline, ...), added stage by stage, each tied back to where it actually shows up in this codebase.

**Convention going forward:** a stage isn't considered done until its ADRs
(if any), its stage doc, the glossary, and `ARCHITECTURE.md` are all
updated. Code without the docs isn't a finished stage.

## Quick start

The app (full architecture in [`ARCHITECTURE.md`](ARCHITECTURE.md), full
build narrative in [`docs/stages/stage-a-foundation-app.md`](docs/stages/stage-a-foundation-app.md)):
a browser frontend, three FastAPI services, Postgres, and Redis, wired as
`api-gateway → orders-service → (redis, inventory-service → postgres)`,
built as separate services specifically so there are real network hops to
trace once Stage B adds OpenTelemetry.

### Run it

```bash
docker compose up --build
```

Then open http://localhost:8000 in a browser, pick a product, and place an
order. Orders and stock levels persist in Postgres across restarts (named
volume `pgdata`).

### Verify it from the command line

```bash
# health checks
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health

# list products
curl http://localhost:8000/api/products

# place an order (product_id 1 = Widget)
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 2}'

# list orders
curl http://localhost:8000/api/orders

# try to over-order (expect 409 Insufficient stock)
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 3, "quantity": 999}'
```

### Tear down

```bash
docker compose down        # stop containers, keep data
docker compose down -v     # stop containers and wipe the postgres volume
```

## Next: Stage B

Add OpenTelemetry SDKs to each service (auto-instrumentation for FastAPI /
httpx / SQLAlchemy / Redis, plus a couple of manual spans) and print
traces/logs to the console so we can see what a span and a trace actually
look like before adding a Collector.
