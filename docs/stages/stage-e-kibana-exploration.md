# Stage E — Explore the data in Kibana

Status: **Complete** (mechanism proven; UI exploration is ongoing/self-directed)

## What

Confirmed that the telemetry landing in Elasticsearch since Stage D is
genuinely explorable through Kibana's own UI — not just via `curl` — and
identified which Kibana surfaces actually work with our data versus which
ones need a component we deliberately don't have.

## Why

Stage D proved the data *exists* in Elasticsearch via direct API calls.
Stage E's job is the human side of that: can you actually look at it,
follow a request across services, and connect a log line to the trace
that produced it, using the tool (Kibana) a real operator would use day
to day.

## What was confirmed

- **Discover** reliably works against our raw data streams
  (`logs-generic.otel-default`, `traces-generic.otel-default`,
  `metrics-generic.otel-default`) — confirmed by querying `trace_id` and
  `status.code` fields directly and getting back real documents, including
  the deliberately-generated error cases (409 insufficient stock, 404
  product not found) from a batch of test traffic.
- Error traces are distinguishable from success: `status.code : "Error"`
  returned exactly 6 span documents matching our 2 deliberately-failed
  requests, out of 167 total spans in that window.
- Kibana's default Discover experience is now **ES|QL-first** (a
  `FROM ... | WHERE ...` query bar), with a **"Switch to Classic"** option
  for the older point-and-click search bar. Most third-party tutorials
  still assume Classic mode — worth switching to it while learning the
  basics, independent of this project.

## Known limitation: "Applications" (APM) UI

Kibana's full Applications UI (Service Inventory, Service Map with
health indicators) depends on APM-specific *derived* metrics that a
component called the APM connector produces from raw traces. We don't
run that component — ADR-0008 deliberately chose the plain upstream
`otel/opentelemetry-collector-contrib` distribution over Elastic's own
EDOT distribution, for learning-purity reasons. Consequence: Applications
may show no services, or incomplete data, even though the raw trace data
is fully present and queryable in Discover. This isn't a bug to chase --
it's the direct, expected consequence of ADR-0008, and it means
**Discover and ES|QL are this project's primary lens**, not the
Applications UI. This matters for Stage F too (see that stage's doc for
the resulting pivot).

## How to verify (self-directed)

```
# Discover, data view traces-*, time range "Last 15 minutes"
status.code : "Error"

# then, with one trace_id from those results:
trace_id : "<id>"

# switch data view to logs-*, same query -- same trace_id's log lines appear
```

ES|QL equivalent, usable directly in Discover's ES|QL mode:
```
FROM traces-generic.otel-default
| WHERE status.code == "Error"
| KEEP @timestamp, trace_id, resource.attributes.service.name, name
| SORT @timestamp DESC
| LIMIT 20
```

## Learning resources used

Kibana's UI turned out to be a bigger learning curve than the pipeline
itself for a first-time user. Pointed to Elastic's own official
interactive tutorials rather than third-party video, since Elastic's own
UI has changed enough recently (observed firsthand during Stage D) that
freshness matters more than usual:
- [Explore fields and data with Discover](https://www.elastic.co/docs/explore-analyze/discover/discover-get-started)
- [Learn data exploration and visualization with Kibana](https://www.elastic.co/docs/explore-analyze/kibana-data-exploration-learning-tutorial)
- [Get started with ES|QL](https://www.elastic.co/docs/explore-analyze/discover/try-esql)

## What's next

Stage F: anomaly detection. See that stage's doc for why it isn't simply
"turn on the built-in APM anomaly detection toggle" (that toggle lives
inside the Applications UI we just established doesn't recognize our
services) and what we did instead.
