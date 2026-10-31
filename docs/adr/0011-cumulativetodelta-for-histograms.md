# ADR-0011: `cumulativetodelta` processor to stop Elasticsearch from dropping histogram metrics

Date: 2026-10-29
Status: Accepted

## Context

Once telemetry was confirmed reaching Elasticsearch, the Collector's own
logs showed a recurring warning from the `elasticsearch` exporter:

```
validation errors ... error: dropping cumulative temporality histogram "http.server.duration"
dropping cumulative temporality histogram "http.server.response.size"
dropping cumulative temporality histogram "http.server.request.size"
dropping cumulative temporality histogram "http.client.duration"
```

This is a documented limitation: the Elasticsearch exporter cannot store
histogram metrics reported with *cumulative* temporality (the OTel SDK's
default for histograms). They were being silently dropped -- accepted by
the exporter, logged as a warning, never indexed. `http.server.duration`
and the other request-size/duration histograms are exactly the metrics
most worth having for later stages (e.g. noticing latency regressions
during chaos testing), so silently losing them was worth fixing rather
than accepting.

## Decision

Added a `cumulativetodelta` processor to the metrics pipeline only
(traces/logs don't reference it), positioned after `memory_limiter` and
before `batch`:

```yaml
processors:
  cumulativetodelta: {}
...
service:
  pipelines:
    metrics:
      processors: [memory_limiter, cumulativetodelta, batch]
```

It converts cumulative sums/histograms to delta temporality before they
reach the `elasticsearch` exporter, so they're stored instead of dropped.

## Alternatives considered

- **Configure the app-side OTel SDK to emit delta temporality directly**
  (via `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta` on each
  service). Would avoid the conversion step entirely, but means touching
  every service's environment again for a backend-specific concern --
  exactly the kind of change the Collector is supposed to absorb so the
  app side doesn't need to know what's downstream (see Stage C's
  rationale). Converting at the Collector keeps that boundary intact.
- **Accept the data loss.** Rejected -- these are exactly the metrics
  most useful for noticing a slow response during Stage G's chaos
  exercises; losing them silently would undermine that stage before it
  even starts.

## Consequences

- Confirmed fix by restarting the Collector, placing a fresh order, and
  checking: (a) zero "dropping cumulative temporality" warnings in the
  Collector's logs after the restart, and (b) `metrics.http.server.duration`
  exists as an indexed `histogram`-typed field in
  `metrics-generic.otel-default`, confirmed via an `exists` + aggregation
  query against Elasticsearch directly.
- Histogram data is now stored as Elasticsearch's native `histogram`
  field type, which supports aggregations (percentiles, averages) but
  not term-level search -- querying it requires `_search` with an `aggs`
  block, not a plain filter. Worth remembering before assuming a query
  against a histogram field "found nothing."

## Revisit when

If a future metric needs cumulative temporality preserved specifically
(uncommon), exclude it via `cumulativetodelta`'s `include`/`exclude`
settings rather than removing the processor entirely.
