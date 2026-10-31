# Architecture (current state)

This file reflects the system **as it exists right now**. It gets rewritten
in place as each stage adds to the system. For the narrative of how we got
here and why, see `docs/stages/`. For why specific non-obvious choices were
made, see `docs/adr/`.

Last updated: end of Stage 2 (2026-10-31) -- this is the final planned stage.

## System diagram

```
                     ┌──────────────┐
   browser  ───────▶ │ api-gateway  │  :8000
                     │ (+ frontend) │
                     └──────┬───────┘
                            │ /api/*
                            ▼
                     ┌──────────────┐
                     │orders-service│  :8001
                     └──┬────────┬──┘
                        │        │
              ┌─────────▼─┐   ┌──▼──────────────┐
              │   redis   │   │ inventory-service│  :8002
              │ (price    │   └─────────┬────────┘
              │  cache)   │             │
              └───────────┘             ▼
                                   ┌───────────┐
                                   │ postgres  │  :5432
                  orders.orders ◀──┤           ├──▶ inventory.products
                                   └───────────┘

   api-gateway, orders-service, inventory-service
          │ OTLP/gRPC (traces, metrics, logs)
          ▼
   ┌─────────────────┐
   │  otel-collector  │  :4317 (grpc) / :4318 (http)
   │  traces/logs:  otlp→memory_limiter→batch→[debug, elasticsearch]
   │  metrics:      otlp→memory_limiter→cumulativetodelta→batch→[debug, elasticsearch]
   └────────┬────────┘
            │ HTTPS (Bulk API, api_key auth)
            ▼
   Elastic Cloud (serverless project)
   data streams: logs-generic.otel-default,
                 traces-generic.otel-default,
                 metrics-generic.otel-default

Credentials (ELASTIC_ENDPOINT, ELASTIC_API_KEY) live in a gitignored
.env, loaded by docker compose into the otel-collector container only --
see ADR-0009.

A standing ML job (service_request_spikes) runs inside the same Elastic
Cloud project, independent of the app/Collector -- reads
traces-generic.otel-default via its own datafeed, not through the
Collector pipeline above. See Stage F.

inventory-service exposes GET/POST /chaos (mode: none|slow|query_timeout|
connection_failed|pool_exhausted) for fault injection on the stock-
reservation path only. See Stage G.

Stage 2 adds a second Elasticsearch destination, parallel to the main
OTel-native logs stream:

   otel-collector logs pipeline
     -> transform/classify_errors (tags error.category-bearing logs)
     -> elasticsearch exporter (dynamic index-attribute routing)
     -> logs.obs-shop.errors (parent, default_pipeline = reroute)
          -> logs.obs-shop.errors.query_timeout
          -> logs.obs-shop.errors.connection_failed
          -> logs.obs-shop.errors.pool_exhausted
          -> logs.obs-shop.errors.unavailable
          (unmatched error.category values stay in the parent -- catch-all)

   + a standing ML job, obs_shop_error_spikes, over logs.obs-shop.errors*
```

## Telemetry pipeline

- **App side** (Stage B): every service runs under `opentelemetry-instrument`.
  Automatic spans for inbound HTTP (FastAPI), outbound HTTP (httpx), DB
  queries + connection pool gauges (SQLAlchemy), and (orders-service only)
  Redis commands. Two hand-written spans (`get_product_cached`,
  `reserve_stock`) and two hand-written counters (`orders.created`,
  `orders.cache_lookup`). Log lines carry `trace_id`/`span_id`.
- **Collector side** (Stage C): every service exports OTLP/gRPC to
  `otel-collector:4317` instead of printing to its own console. The
  Collector's pipeline (`otel-collector/config.yaml`) is
  `otlp receiver → memory_limiter → batch → debug exporter` for all three
  signals. All three services' telemetry for one request now converges in
  one place (`docker compose logs otel-collector`), confirmed by shared
  `trace_id`s across `service.name` values `api-gateway`,
  `orders-service`, `inventory-service`.
- Configuration for both lives in `docker-compose.yml`'s `x-otel-env`
  anchor (app side) and `otel-collector/config.yaml` (Collector side);
  see `docs/stages/stage-b-opentelemetry-instrumentation.md` and
  `docs/stages/stage-c-otel-collector.md`.
- **Elastic Cloud side** (Stage D): the Collector's `elasticsearch`
  exporter writes into a real Elastic Cloud serverless project, using
  OTel-native mapping (default mode) so data lands in
  `logs-generic.otel-default`, `traces-generic.otel-default`,
  `metrics-generic.otel-default`. A `cumulativetodelta` processor runs
  ahead of it in the metrics pipeline only, so histogram metrics
  (`http.server.duration` etc.) are stored instead of silently dropped
  (Elasticsearch can't store cumulative-temporality histograms). Verified
  by searching Elasticsearch directly for a real order's `trace_id` and
  finding all 29 spans across all three services; see
  `docs/stages/stage-d-elastic-cloud.md`.
- **Anomaly detection** (Stage F): a standing ML job
  (`service_request_spikes`, `high_count` detector partitioned by
  `service.name`, `bucket_span: 1m`) runs directly against
  `traces-generic.otel-default` via its own datafeed — created through
  Elasticsearch's `_ml` API directly, not Kibana's built-in per-service
  APM anomaly toggle (that UI doesn't recognize our services; see
  ADR-0012). Currently under-trained (5 non-empty buckets out of 1119) and
  didn't flag a deliberate 40-request burst — see
  `docs/stages/stage-f-anomaly-detection.md` for why that's an expected,
  instructive result rather than a bug.
- **Chaos engineering** (Stage G): `inventory-service` exposes
  `GET/POST /chaos` to toggle real fault injection
  (`slow`/`query_timeout`/`connection_failed`/`pool_exhausted`) on the
  stock-reservation write path, plus real outages via stopping the
  `postgres`/`redis` containers directly. All five of the original
  "deliberate landmine" ADRs (0003, 0004, 0005) got exercised for real
  here. Also where a genuine bug was found and fixed: api-gateway's
  `/api/orders` endpoint was blocking FastAPI's event loop on a
  synchronous HTTP call (ADR-0014) — not a landmine, an accident, fixed.
  See `docs/stages/stage-g-chaos-engineering.md`.
- **Elastic Streams pattern** (Stage 2): `error.category` is set directly
  in application code (`extra={"error.category": ...}` on the relevant
  `logger.error(...)` calls), tagged for separate routing by a Collector
  `transform` processor, and fanned into per-category child streams by a
  real Elasticsearch ingest pipeline (`logs.obs-shop.errors@reroutes`),
  mirroring the reference Medium article. An ML job
  (`obs_shop_error_spikes`) runs over the whole hierarchy the same way
  Stage F's job did, with the same under-trained-model limitation found
  again. See `docs/stages/stage-2-elastic-streams.md`.

## Components

- **api-gateway** — FastAPI. Single public entry point. Serves the static
  frontend (`services/api-gateway/static/`) and proxies `/api/products`,
  `/api/orders` to the backend services. No business logic, no DB access.
- **orders-service** — FastAPI. Owns order placement: price lookup
  (Redis cache-aside, falling back to inventory-service), stock
  reservation (calls inventory-service), order persistence (own schema in
  Postgres).
- **inventory-service** — FastAPI. Owns product/stock data. The only
  service that writes to the `inventory` schema.
- **postgres** — one instance, two schemas (`orders`, `inventory`), each
  written to by exactly one service. Named volume `pgdata` for persistence
  across restarts.
- **redis** — single instance, used only by orders-service, as an
  optimization (not a source of truth).

## Request path: place an order

See `docs/stages/stage-a-foundation-app.md` for the full step-by-step walk.
Short version: `browser → api-gateway → orders-service → {redis |
inventory-service → postgres} → orders-service → postgres → back up the
chain`.

## Repo layout

```
.env                          # gitignored -- ELASTIC_ENDPOINT, ELASTIC_API_KEY (local only)
.env.example                  # committed template, no real values
docker-compose.yml
otel-collector/
  config.yaml                # receiver/processor/exporter pipeline config
db/
  init.sql                   # schema + seed data, mounted into postgres on first boot
services/
  api-gateway/
    app/main.py
    static/                  # frontend: index.html, app.js, style.css
    Dockerfile
    requirements.txt
  orders-service/
    app/main.py
    Dockerfile
    requirements.txt
  inventory-service/
    app/main.py
    app/chaos.py              # fault injection -- GET/POST /chaos (Stage G)
    Dockerfile
    requirements.txt
docs/
  adr/                       # decision records (the "why")
  stages/                   # per-stage build log (the "what" and "how")
  glossary.md                # concept definitions, growing by stage
ARCHITECTURE.md              # this file - current-state system view
README.md                    # entry point, roadmap, quick start
```

## Ports

| Port | Service | Notes |
|---|---|---|
| 8000 | api-gateway | public entry point, frontend + `/api/*` |
| 8001 | orders-service | not meant to be called directly, but exposed for debugging |
| 8002 | inventory-service | same |
| 5432 | postgres | exposed for debugging with `psql` |
| 6379 | redis | exposed for debugging with `redis-cli` |
| 4317 | otel-collector | OTLP gRPC receiver |
| 4318 | otel-collector | OTLP HTTP receiver |

## Known, deliberate landmines (all exercised for real in Stage G)

These are intentional, not bugs — see the linked ADRs:

- DB connection pools are small and fixed (`pool_size=5, max_overflow=0`)
  so pool exhaustion can be reproduced for real later ([ADR-0004](docs/adr/0004-constrained-db-connection-pools.md)).
  Confirmed: 20 concurrent requests produced a real `QueuePool limit of
  size 5 overflow 0 reached` error.
- All endpoints are synchronous, so FastAPI's thread pool is also a real
  limit under load ([ADR-0003](docs/adr/0003-synchronous-request-handling.md)).
- Redis is non-critical: if it's down, orders-service silently falls back
  to calling inventory-service directly, no error surfaces ([ADR-0005](docs/adr/0005-redis-cache-aside-pricing.md)).
  Confirmed: stopping Redis produced zero errors, just a silent shift of
  all lookup load onto inventory-service.

Not a landmine, a real bug found via chaos testing and fixed: api-gateway's
`/api/orders` was `async def` but called synchronous `httpx.post()`
inside it, blocking the entire event loop and serializing every
concurrent order regardless of product ([ADR-0014](docs/adr/0014-fix-api-gateway-blocking-event-loop.md)).
