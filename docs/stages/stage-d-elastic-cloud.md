# Stage D — Point the Collector at an Elastic Cloud trial

Status: **Complete**
Related ADRs: [0009](../adr/0009-secrets-via-gitignored-env-file.md), [0010](../adr/0010-direct-elasticsearch-endpoint.md), [0011](../adr/0011-cumulativetodelta-for-histograms.md)

## What

The Collector now has a second exporter, `elasticsearch`, sending
everything it receives into a real Elastic Cloud (serverless) project —
alongside the existing `debug` exporter, so both can be cross-checked.
Telemetry now leaves `docker compose` entirely for the first time.

## Why

Stages A-C built a complete local loop with nowhere durable for the data
to live or be searched. Stage D is the first time this project's
telemetry becomes something you could actually run a query against,
build a dashboard on top of, or (Stage F onward) run anomaly detection
over — the entire point of the original goal statement ("forward your
traces, metrics, and logs to Elasticsearch").

## How it works

### Credentials

`.env` (gitignored) holds `ELASTIC_ENDPOINT` and `ELASTIC_API_KEY`.
`docker-compose.yml` passes them into the `otel-collector` container;
`otel-collector/config.yaml` reads them via `${env:...}` substitution.
See ADR-0009 for why `.env` over a vault, for this project's scale.

### Exporter config

```yaml
exporters:
  elasticsearch:
    endpoints: ["${env:ELASTIC_ENDPOINT}"]
    api_key: "${env:ELASTIC_API_KEY}"
```

No `mapping.mode` set — the exporter's current default (`otel`) writes
into OTel-native data streams Kibana understands natively:
`logs-generic.otel-default`, `traces-generic.otel-default`,
`metrics-generic.otel-default`.

### The metrics fix

A `cumulativetodelta` processor was added to the metrics pipeline only,
after discovering the exporter was silently dropping histogram metrics
(`http.server.duration` and friends) because Elasticsearch can't store
cumulative-temporality histograms. See ADR-0011.

## How to verify

```bash
docker compose up -d   # picks up .env

curl -s -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" -d '{"product_id": 1, "quantity": 1}'

sleep 15

# From a shell with .env loaded (never paste the API key anywhere else):
set -a; source .env; set +a

# 1. Confirm the OTel-native data streams exist
curl -s -H "Authorization: ApiKey ${ELASTIC_API_KEY}" "${ELASTIC_ENDPOINT}/_data_stream"

# 2. Grab a trace_id from orders-service's logs, then search for it directly
curl -s -H "Authorization: ApiKey ${ELASTIC_API_KEY}" -H "Content-Type: application/json" \
  "${ELASTIC_ENDPOINT}/traces-generic.otel-default/_search?pretty" \
  -d '{"query":{"term":{"trace_id":"<trace_id>"}},"size":30}'
```

**Actually run on 2026-10-29:** placed an order (`order_id: 7`,
`trace_id=657338a33012e0e94e1e4acf9486605a`). `_data_stream` returned
`logs-generic.otel-default`, `metrics-generic.otel-default`,
`traces-generic.otel-default`. Searching for that exact `trace_id`
returned **29 spans**, spanning all three services
(`api-gateway`, `orders-service`, `inventory-service`), including both
hand-written spans from Stage B (`get_product_cached`, `reserve_stock`)
and the full set of automatic ones (FastAPI, httpx, SQLAlchemy, Redis).
Document counts at that point: 6 log documents, 493 metric documents, 29
trace documents.

After adding the `cumulativetodelta` fix and restarting the Collector,
placed another order and confirmed zero `"dropping cumulative
temporality"` warnings in the Collector's logs, and confirmed
`metrics.http.server.duration` exists as an indexed `histogram`-typed
field via an `exists` + aggregation query (plain term search on a
histogram field correctly errors with "field do not support searching,
use dedicated aggregations instead" — that error is itself proof the
field is indexed, not evidence of a problem).

## Troubleshooting log (this stage was a real journey)

**1. Elastic's sign-up flow has moved to serverless projects by
default.** The "Create deployment" button from Elastic's own older docs
wasn't what showed up — new trial accounts get funneled into "Create
project" instead. Not a blocker, just an outdated assumption on my part;
both paths expose the same Cloud ID / API key / endpoint concepts
underneath.

**2. The Fleet/Integrations catalog ("Add Observability data") is a
different ingestion path, not what we needed.** That screen's tiles
(AWS, Azure, Docker, Kubernetes...) are for Elastic-Agent-collected data,
not for a standalone Collector forwarding its own OTLP data. Its
"OpenTelemetry" entry, however, did hand out an endpoint + API key
quickly — just not the right *kind* of endpoint (see next point).

**3. The endpoint from that OpenTelemetry quickstart screen was a
write-only ingest gateway, not the real cluster.** Its root response
(`GET /`) returned `"name": "managed-inputs"` — not a real node name —
and `_search`/`_cat/indices` against it both returned plain-text 404s,
not Elasticsearch-shaped errors. Meanwhile, `GET _data_stream` run
*inside Kibana's own Dev Tools* against the real project came back
`{"data_streams": []}` even after multiple orders and generous waits —
proof the writes weren't landing where this Kibana could see them.
Diagnosed by comparing the gateway's root response shape against a known
real Elasticsearch root response, not by any error message directly
saying "wrong endpoint." See ADR-0010.

**4. The real endpoint was found via Kibana's Console settings, not
Connection Details.** "Help icon → Connection Details" (the standard
documented path) either wasn't where expected or wasn't checked
correctly a couple of times; what actually worked was **Dev Tools →
Console settings → "Elasticsearch host"** — guaranteed correct because
Dev Tools' own queries were already succeeding against it.

**5. A typo on the first paste into `.env`** produced `curl: (6) Could
not resolve host` — diagnosed by checking the raw value directly (the
endpoint isn't a secret, so this was safe to inspect directly) rather
than continuing to guess from symptoms.

**6. Docker Desktop's daemon was down** for one `docker compose up`
attempt (`Cannot connect to the Docker daemon`) — unrelated to anything
we'd changed; resolved by starting Docker Desktop and retrying once the
daemon responded to `docker ps`.

**7. Elasticsearch silently dropped histogram metrics** — covered above
and in ADR-0011. The general lesson across this whole stage: "no error on
our side" is not the same as "it worked" — the only real confirmation is
querying the destination directly, not just watching the source for the
absence of complaints.

## What's next

Stage E: explore this data properly from inside Kibana — trace
waterfalls, a service map, Discover queries, and log-to-trace
navigation — rather than hand-written `curl` queries against raw indices.
