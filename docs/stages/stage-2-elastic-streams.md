# Stage 2 — Elastic Streams / ML pattern from the reference article

Status: **Complete**
Related ADRs: [0015](../adr/0015-error-classification-on-logs.md), [0016](../adr/0016-collector-side-dynamic-routing.md), [0017](../adr/0017-explicit-keyword-mappings-for-ml.md)

Reference: [From Log Chaos to Real-Time Anomaly Detection with Elastic Streams](https://medium.com/@sdakwoji/from-log-chaos-to-real-time-anomaly-detection-with-elastic-streams-068ac23380cf)

## What

The full pattern from the reference article, built on our own real
telemetry instead of synthetic bulk-inserted documents: application-level
error classification → Collector-side routing into a dedicated hierarchy
→ Elasticsearch ingest-pipeline reroute into per-category child streams
→ a catch-all for anything unclassified → an ML anomaly-detection job
over the whole hierarchy → ES|QL visualization → (as reference
configuration) the article's three-alert pattern.

## Why

This is the project's original end goal, stated at the very first
message: build the OTel pipeline, then apply this specific article's
pattern on top of it. Everything since Stage A was building the "on top
of" part. Our chaos categories (`query_timeout`, `connection_failed`,
`pool_exhausted`, and a real `unavailable`) were deliberately designed in
Stage G to match the article's own four categories, specifically so this
stage would have real, not synthetic, classified error data to work
with.

## How it works

### 1. Classify at the source (our departure from the article)

The article infers `error.category` from log message text via an
ingest-pipeline `set` processor, because it can't change the producer.
We can — we wrote the producer. `services/inventory-service/app/main.py`
and `services/orders-service/app/main.py` set `error.category` directly
via `logger.error(..., extra={"error.category": "pool_exhausted"})`,
right where each failure is already being handled. See ADR-0015.

### 2. Collector-side routing into a dedicated hierarchy

Rather than modifying Elastic's already-working, managed
`logs-generic.otel-default` template (too risky, see ADR-0016), a
`transform` processor in `otel-collector/config.yaml` tags matching
log records for separate routing:

```yaml
transform/classify_errors:
  log_statements:
    - context: log
      statements:
        - set(log.attributes["elasticsearch.index"], "logs.obs-shop.errors") where log.attributes["error.category"] != nil
```

The `elasticsearch` exporter's dynamic index-attribute routing mode
reads that tag and sends only those documents elsewhere; everything
without the tag is unaffected.

### 3. The parent + catch-all (Elasticsearch ingest pipeline, the real thing)

```
PUT _ingest/pipeline/logs.obs-shop.errors@reroutes
{
  "processors": [
    { "reroute": { "destination": "logs.obs-shop.errors.query_timeout",
                    "if": "ctx.attributes != null && ctx.attributes['error.category'] == 'query_timeout'" } },
    { "reroute": { "destination": "logs.obs-shop.errors.connection_failed", "if": "..." } },
    { "reroute": { "destination": "logs.obs-shop.errors.pool_exhausted",   "if": "..." } },
    { "reroute": { "destination": "logs.obs-shop.errors.unavailable",      "if": "..." } }
    // no else -- unmatched documents stay in the parent, unchanged
  ]
}
```

set as the parent data stream's `index.default_pipeline`, via an index
template (`logs.obs-shop.errors`, priority 500, `index.mode: logsdb`).
Four child index templates (`logs.obs-shop.errors.<category>`, same
priority, same `logsdb` mode) compose a shared component template
(`obs-shop-errors-mappings`) for consistent mappings.

### 4. The ML job

```
PUT _ml/anomaly_detectors/obs_shop_error_spikes
{
  "analysis_config": {
    "bucket_span": "1m",
    "detectors": [{
      "function": "high_count",
      "by_field_name": "attributes.error.category",
      "partition_field_name": "resource.attributes.service.name"
    }],
    "influencers": ["resource.attributes.service.name", "attributes.error.category"]
  },
  "data_description": { "time_field": "@timestamp" }
}

PUT _ml/datafeeds/datafeed-obs_shop_error_spikes
{
  "job_id": "obs_shop_error_spikes",
  "indices": ["logs.obs-shop.errors*"],
  "query": { "match_all": {} },
  "query_delay": "30s",
  "frequency": "30s"
}
```

`by_field_name: attributes.error.category` is our direct equivalent of
the article's `stream.name` detector — same idea (which category spiked),
applied to our own classification field instead of a Streams-feature
meta-field.

## How to verify

```bash
# 1. Confirm error.category is a real, queryable log attribute
curl -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "Content-Type: application/json" \
  "$ELASTIC_ENDPOINT/logs-generic.otel-default/_search" \
  -d '{"query":{"exists":{"field":"attributes.error.category"}},"size":1}'

# 2. Confirm per-category routing landed in the right child streams
for ds in logs.obs-shop.errors logs.obs-shop.errors.query_timeout \
          logs.obs-shop.errors.connection_failed logs.obs-shop.errors.pool_exhausted \
          logs.obs-shop.errors.unavailable; do
  curl -H "Authorization: ApiKey $ELASTIC_API_KEY" "$ELASTIC_ENDPOINT/$ds/_count"
done

# 3. ES|QL breakdown
curl -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "Content-Type: application/json" \
  "$ELASTIC_ENDPOINT/_query?format=txt" \
  -d '{"query": "FROM logs.obs-shop.errors* | STATS count = COUNT(*) BY category = attributes.error.category, svc = resource.attributes.service.name | SORT count DESC"}'
```

**Actually run on 2026-10-31**, after generating real chaos traffic for
every category:

| category | service | count |
|---|---|---|
| query_timeout | orders-service | 16 |
| pool_exhausted | inventory-service | 10 |
| connection_failed | inventory-service | 1 |
| unavailable | orders-service | 1 |
| unavailable | inventory-service | 1 |
| connection_failed | orders-service | 1 |
| something_never_seen_before | inventory-service | 1 (catch-all test) |

Notice `pool_exhausted` is **exclusively** inventory-service (it's the
only service with that failure mode) while `query_timeout` is mostly
orders-service (it's the one whose httpx call actually times out) — and
`connection_failed`/`unavailable` appear from **both** services, each
reporting its own vantage point on the same underlying incidents. The
catch-all category is present and correctly isolated to the parent, not
lost or misfiled.

Catch-all, verified explicitly: indexed a document with
`error.category: "something_never_seen_before"` directly into
`logs.obs-shop.errors` — landed in `.ds-logs.obs-shop.errors-2026.10.31-000001`
(the parent's own backing index), confirmed via `_data_stream` and
`_count`, not in any child stream.

## Troubleshooting log

**The article's own "mapping gotcha" lesson, reproduced firsthand.**
Starting the ML datafeed failed: `cannot retrieve field
[attributes.error.category] because it has no mappings` — despite that
exact field already working fine in plain `_search` queries throughout
this stage. Checked `_field_caps` directly (the article's own
recommended check) and confirmed: mapping the whole `attributes` object
as Elasticsearch's `flattened` type makes sub-paths queryable but not
individually aggregatable. Fixed by mapping `attributes.error.category`
and `resource.attributes.service.name` as explicit `keyword` fields
(ADR-0017). Since component template changes don't apply retroactively,
the (small, disposable) existing data streams were deleted and
recreated rather than migrated — directly consistent with the article's
own Lesson 4 about not being able to backfill into child streams.

**A genuine classification race, left as a documented finding, not a
bug.** orders-service's httpx timeout to inventory-service (5.0s) and
inventory-service's own SQLAlchemy `pool_timeout` (5.0s) are numerically
identical. During a `pool_exhausted` burst, which category a given
failed request gets — `pool_exhausted` (inventory-service's clock fired
first) or `query_timeout` (orders-service's clock fired first) — depends
on microsecond-level timing, not a classification bug. See ADR-0015.
Real production systems should stagger these deliberately (caller
timeout meaningfully larger than callee timeout); this project's
identical values made the race visible rather than hidden.

**The "generic 500 masks everything" problem from Stage G, actually
fixed this time.** Stage G documented but deliberately didn't fix 3
scenarios where a specific failure degraded into an uninformative
generic 500 by the time it reached the caller. Stage 2 needed real
classification to survive the trip between services to build a
meaningful Streams hierarchy, so inventory-service's classified 5xx
responses now carry `{"message": ..., "error_category": ...}` as a
structured body, and orders-service reads it instead of blindly calling
`raise_for_status()`. Verified: a `connection_failed` chaos request now
returns a clean `503 {"detail":{"message":"Inventory service
error","error_category":"connection_failed"}}` end to end, not a
content-type-mismatched generic 500.

## Alerting (reference configuration, not live-created)

The article's three-rule pattern, adapted to our fields. Not created via
the Kibana Alerting API in this session — that API lives on the Kibana
endpoint specifically (a different host than the Elasticsearch endpoint
this project already struggled to pin down correctly in Stage D), and
creating it blind without verifying that endpoint first risked repeating
that same multi-turn detour. Documented here, ready to create via
Kibana's Alerting UI or API once that endpoint is in hand:

**1. Volume/outage alert** (`.es-query` rule type) — the dependable, hard-threshold catcher:
```json
{
  "name": "obs-shop error volume spike",
  "rule_type_id": ".es-query",
  "schedule": { "interval": "5m" },
  "params": {
    "searchType": "esQuery",
    "index": ["logs.obs-shop.errors*"],
    "timeField": "@timestamp",
    "esQuery": "{\"query\":{\"match_all\":{}}}",
    "timeWindowSize": 30, "timeWindowUnit": "m",
    "thresholdComparator": ">", "threshold": [50]
  }
}
```

**2. Forwarding-broken alert** — pipeline-health, not content:
watch whether `logs-generic.otel-default` is accumulating documents with
`error.category` set but age beyond a few minutes (would mean the
Collector's transform processor, or the exporter's dynamic routing,
stopped working) — the same role the article's "errors piling up in the
raw index unforwarded" check plays, adapted to this project's
Collector-side routing instead of an Elasticsearch-side one.

**3. ML anomaly alert** — fires on `obs_shop_error_spikes`'s results once
it has enough real history to score meaningfully (see Stage F and this
stage's own under-trained result below).

## Known limitation: the ML job needs more history than one session can generate

Consistent with Stage F's finding: `obs_shop_error_spikes` has only 10
one-minute buckets, 1 of them non-empty (27 events, our `pool_exhausted`
burst), `anomaly_score: 0.0`. Not enough real observations to build a
trustworthy baseline — same root cause as Stage F, now confirmed a
second time on a second job. This is the article's own "Lesson 1 and 2"
territory: a real production system accumulates this history for free
over days; a learning session generating test traffic by hand does not,
and shouldn't pretend otherwise by tuning the job to show a score just
to get a green result.

## What's next

This completes the project's full originally-scoped plan: Stages A-G
(the OpenTelemetry pipeline, end to end) plus Stage 2 (the reference
article's pattern, built on real data instead of synthetic). See the
root `README.md` for the complete roadmap and a map of all the
documentation this project produced along the way.
