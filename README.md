# OpenTelemetry → Elastic Observability Lab

A hands-on, end-to-end observability project: a small full-stack app, fully
instrumented with **OpenTelemetry**, shipping traces, metrics, and logs
through an **OpenTelemetry Collector** into **Elastic Cloud** — then used to
practice the thing observability actually exists for: **diagnosing real
failures**.

It's built as a learning lab, but not a toy — every stage is verified against
real data (not "it ran without erroring"), every non-obvious decision is
written down as an ADR, and the failures encountered along the way (including
a genuine concurrency bug and five live browser-SDK bugs) are documented as
honestly as the successes.

## What it demonstrates

- **Distributed tracing** across a browser frontend and three backend
  services — one request produces a single ~29-span trace, from the browser's
  own click down to individual SQL statements.
- **Log ↔ trace correlation** — every log line carries the `trace_id`/`span_id`
  of the request that produced it.
- **An OpenTelemetry Collector** (receivers → processors → exporters) as the
  single telemetry sink in front of the apps, exporting to Elasticsearch.
- **Chaos engineering** — on-demand, *genuine* fault injection (real query
  timeouts, connection failures, connection-pool exhaustion, full dependency
  outages), then diagnosing each one from the telemetry.
- **The Elastic Streams pattern** — error logs classified by category and
  routed through a real Elasticsearch ingest pipeline into per-category child
  data streams, with a catch-all, mirroring
  [this Elastic Streams article](https://medium.com/@sdakwoji/from-log-chaos-to-real-time-anomaly-detection-with-elastic-streams-068ac23380cf).
- **ML anomaly detection** jobs over that telemetry — including the honest,
  firsthand lesson about *why* ML alone is an unreliable outage detector
  without a real baseline (and why hard-threshold alerts remain the dependable
  catcher).

## Architecture at a glance

```
browser (OTel Web SDK)
   │                        ┌──────────────┐     ┌──────────────────┐
   └── fetch() ───────────▶ │ api-gateway  │────▶│  orders-service   │──┐
       (traceparent)        └──────────────┘     └──────────────────┘  │
                                   │                   │        │       ▼
   all services + browser          │                  ▼        ▼   ┌────────┐
   export OTLP to ───┐             │              ┌───────┐ ┌──────┐│postgres│
                      ▼            ▼               │ redis │ │inven-││        │
              ┌───────────────┐                   │(cache)│ │tory  │└────────┘
              │ otel-collector │                  └───────┘ │-svc  │
              └───────┬────────┘                            └──────┘
                      │ OTLP → Bulk API
                      ▼
              Elastic Cloud (Elasticsearch + Kibana)
              traces / metrics / logs  +  error-stream hierarchy  +  ML jobs
```

Full detail in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Quick start

Requires **Docker** (with Compose) and — for the Elastic Cloud stages — a free
[Elastic Cloud trial](https://cloud.elastic.co/registration).

```bash
# 1. Run the whole stack locally (app + Collector + Postgres + Redis)
docker compose up --build

# 2. Open the shop frontend and place an order
open http://localhost:8000

# 3. (optional) Ship telemetry to Elastic Cloud: copy the template,
#    fill in your trial's endpoint + API key, then restart.
cp .env.example .env     # then edit .env with real values
docker compose up -d
```

The app runs fully locally without Elastic Cloud — telemetry just prints to
the Collector's console until you add credentials. See
[`docs/stages/stage-d-elastic-cloud.md`](docs/stages/stage-d-elastic-cloud.md)
for how to get the endpoint and API key.

## Tech stack

Python / FastAPI · OpenTelemetry (Python SDK + Web SDK) · OpenTelemetry
Collector (contrib) · Elasticsearch + Kibana (Elastic Cloud serverless) ·
PostgreSQL · Redis · Docker Compose

## How this project is documented

It's documented the way a real production system should be — so that six
months from now, it tells you what exists, why it's built that way, and how to
operate it, without reconstructing any of it from memory:

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — the system as it exists *right now*.
- **[`docs/stages/`](docs/stages/)** — a build log, one doc per stage: what was
  built, how to verify it, and what went wrong along the way.
- **[`docs/adr/`](docs/adr/)** — Architecture Decision Records: the *why* behind
  each non-obvious choice, with alternatives and trade-offs.
- **[`docs/glossary.md`](docs/glossary.md)** — every concept defined and tied
  back to where it actually shows up in the code.
- **[`docs/esql-cheatsheet.md`](docs/esql-cheatsheet.md)** — learn the ES|QL
  queries used throughout, with exercises, an answer key, and learning links.
- **[`docs/slo.md`](docs/slo.md)** and **[`docs/incidents/`](docs/incidents/)** —
  the SLOs, plus blind incident drills with blameless postmortems.

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
| J | **Done** (exported to `kibana/dashboards/`) | RED-method Kibana dashboard (Rate/Errors/Duration vs SLOs), used in 3 blind incident drills | [stage-j-red-dashboard.md](docs/stages/stage-j-red-dashboard.md) |
| K | **Started, ongoing** | Let the ML jobs (`service_request_spikes`, `obs_shop_error_spikes`) mature with real history | [stage-k-ml-maturity.md](docs/stages/stage-k-ml-maturity.md) |

> **Documentation convention:** a stage isn't considered done until its ADRs
> (if any), its stage doc, the glossary, and `ARCHITECTURE.md` are all updated.
> Code without the docs isn't a finished stage.

## Try it out

Once the stack is up (`docker compose up --build`), exercise it from the
command line:

```bash
# health checks (all three services)
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health

# list products, then place an order (product_id 1 = Widget)
curl http://localhost:8000/api/products
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 2}'

# try to over-order -> expect 409 Insufficient stock
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 3, "quantity": 999}'
```

Inject a failure and watch it propagate through the telemetry (Stage G):

```bash
# make the DB-access layer fail for real, place an order, then reset
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode":"connection_failed"}'
curl -X POST http://localhost:8000/api/orders -H "Content-Type: application/json" -d '{"product_id": 1, "quantity": 1}'
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode":"none"}'
# valid modes: none | slow | query_timeout | connection_failed | pool_exhausted
```

Tear down:

```bash
docker compose down        # stop containers, keep data
docker compose down -v     # stop containers and wipe the postgres volume
```
