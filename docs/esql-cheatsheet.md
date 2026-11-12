# ES|QL cheat-sheet (built from this project's real queries)

ES|QL is Elasticsearch's pipe-style query language. You never write one from a blank page: you start with a question in plain words and translate each phrase into a command. Every query used in the incident drills in `docs/incidents/` follows the shape below. If you know SQL, most of it transfers directly.

Every query here was run against this project's data. The names (`traces-generic.otel-default`, `logs.obs-shop.errors*`, `api-gateway`) are specific to this project; if you rebuild it on a new cluster the same queries work once telemetry is flowing again.

## 1. The mental model

A query is a **table that flows left to right**. `FROM` produces a table of rows. Each `|` hands that table to the next command, which filters, reshapes or summarises it.

```esql
FROM logs.obs-shop.errors*
| WHERE @timestamp > NOW() - 5 minutes
| STATS c = COUNT(*) BY category = attributes.error.category
| SORT c DESC
```

| line | plain meaning |
|---|---|
| `FROM logs.obs-shop.errors*` | look at these logs (`*` matches all the child streams) |
| `WHERE @timestamp > NOW() - 5 minutes` | keep only the last 5 minutes |
| `STATS c = COUNT(*) BY category = ...` | count rows, one count per category |
| `SORT c DESC` | biggest first |

**Recipe:** say the question in words ("of the errors in the last 5 minutes, which category is most common?"), then map each phrase: *of the errors* = `FROM`, *in the last 5 minutes* = `WHERE`, *which category, how many* = `STATS ... BY`, *most common* = `SORT ... DESC`.

## 2. The few commands you need

| command | what it does | example |
|---|---|---|
| `FROM` | choose the data | `FROM traces-generic.otel-default` |
| `WHERE` | keep matching rows (`==`, `AND`, `>`) | `WHERE name == "POST /api/orders"` |
| `EVAL` | add a calculated column | `EVAL ms = duration / 1000000` |
| `STATS ... BY` | count/average/percentile, grouped | `STATS p95 = PERCENTILE(ms, 95) BY minute` |
| `KEEP` | choose which columns to show | `KEEP @timestamp, trace_id, ms` |
| `SORT` | order rows | `SORT ms DESC` |
| `LIMIT` | cap the number of rows | `LIMIT 10` |

Functions you'll see: `COUNT`, `SUM`, `MAX`, `PERCENTILE`, `ROUND`, `CASE(condition, value_if_true, value_otherwise)`, `NOW()`, `DATE_TRUNC(1 minute, @timestamp)`.

## 3. Real queries from this project

### Which error category is happening most? (first move in every drill)
```esql
FROM logs.obs-shop.errors*
| WHERE @timestamp > NOW() - 5 minutes
| STATS c = COUNT(*) BY category = attributes.error.category
| SORT c DESC
```
Group by **category only** first. Adding the service too can make a symptom look like the biggest row (see drill 2).

### Open one request: every span in a trace
```esql
FROM traces-generic.otel-default
| WHERE trace_id == "<paste id>"
| EVAL ms = duration / 1000000
| KEEP @timestamp, resource.attributes.service.name, name, status.code, attributes.error.category, attributes.db.statement, ms
| SORT ms DESC
| LIMIT 16
```
`duration` is stored in **nanoseconds**, so dividing by 1,000,000 gives milliseconds. The top row is always the root span; peel layers downward until the time stops shrinking.

### Availability (the SLI): what fraction of orders did not fail?
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders" AND @timestamp > NOW() - 1 hour
| EVAL is_bad = CASE(attributes.http.status_code >= 500, 1, 0)
| STATS total = COUNT(*), bad = SUM(is_bad)
| EVAL availability_pct = ROUND(100.0 * (total - bad) / total, 3)
```
`CASE` turns each row into 1 (a failure) or 0, so `SUM` counts failures. Only 5xx counts as failure: a 409 or 404 is the system correctly rejecting a bad request.

### Orders per minute (the Rate panel)
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders"
| EVAL minute = DATE_TRUNC(1 minute, @timestamp)
| STATS orders = COUNT(*) BY minute
| SORT minute ASC
```
`DATE_TRUNC` rounds each timestamp down to its minute so rows can be grouped into time buckets.

### Latency percentiles (the Duration panel)
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders" AND attributes.http.status_code == 200
| EVAL ms = duration / 1000000
| STATS p50 = PERCENTILE(ms, 50), p95 = PERCENTILE(ms, 95)
```
p50 is the typical request; p95 is how bad the slow 5% are. A big gap between them means a tail problem.

### What is "normal" for each span? (the baseline)
```esql
FROM traces-generic.otel-default
| WHERE @timestamp >= "2026-11-11T12:31:00Z" AND @timestamp <= "2026-11-11T12:40:00Z"
| EVAL ms = duration / 1000000
| STATS typical_ms = ROUND(PERCENTILE(ms, 50), 1), spans = COUNT(*)
    BY svc = resource.attributes.service.name, span = name
| WHERE spans >= 3
| SORT typical_ms DESC
```
Pick a window of healthy traffic. Compare any slow span against its `typical_ms` and ask "how many times bigger?". Nothing needs a threshold decided in advance.

## 4. Gotchas I actually hit

- **Times are UTC.** Kibana displays your local time (UTC+1 here), so 13:26 on screen is `12:26Z` in a query.
- **`NOW() - 5 minutes` moves.** Run it after an incident and it returns nothing. "No results" can mean a wrong window, not "no problem". Use fixed times (`@timestamp >= "2026-11-11T12:25:00Z"`) when investigating afterwards.
- **The Discover time picker also filters ES|QL queries.** In Discover, the picker's range is intersected with your `WHERE`, so a correct query over a fixed incident window returns 0 rows if the picker is on "Last 15 minutes". Set the picker to an absolute range that covers the window (or "Last 3 hours"). Hit during drill 4: 492 orders existed, the queries showed none.
- **Don't name a column with a reserved word.** `first = MIN(...)` failed with a parsing error; rename it (`earliest`).
- **`duration` is nanoseconds**, not milliseconds.
- **Strings use double quotes and `==`:** `name == "POST /api/orders"`.
- **After `STATS`, only the stats columns and the `BY` columns remain.** If you need another column, add it to `BY` or compute it before `STATS`.
- **Check the top of a trace is the root.** The root span is always the slowest because it contains everything.

## 5. Exercises

Change the queries above to answer these. Answers are in section 6; try first.

1. Count errors **per service** instead of per category, over the last day.
2. List orders that took **longer than 1 second**, slowest first, with their `trace_id`.
3. Show the **p99** latency alongside the p50 for successful orders.
4. Show orders per **5-minute** bucket instead of per minute.
5. Which **span names** have the biggest maximum duration across all traces?

## 6. Answer key (tested 2026-11-11; your numbers will differ)

1. ```esql
   FROM logs.obs-shop.errors*
   | WHERE @timestamp > NOW() - 1 day
   | STATS c = COUNT(*) BY svc = resource.attributes.service.name
   | SORT c DESC
   ```
2. ```esql
   FROM traces-generic.otel-default
   | WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders"
   | EVAL ms = duration / 1000000
   | WHERE ms > 1000
   | KEEP @timestamp, trace_id, ms
   | SORT ms DESC
   | LIMIT 10
   ```
3. ```esql
   FROM traces-generic.otel-default
   | WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders" AND attributes.http.status_code == 200
   | EVAL ms = duration / 1000000
   | STATS p50 = PERCENTILE(ms, 50), p99 = PERCENTILE(ms, 99)
   ```
4. ```esql
   FROM traces-generic.otel-default
   | WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders"
   | EVAL bucket = DATE_TRUNC(5 minutes, @timestamp)
   | STATS orders = COUNT(*) BY bucket
   | SORT bucket DESC
   ```
5. ```esql
   FROM traces-generic.otel-default
   | EVAL ms = duration / 1000000
   | STATS slowest = MAX(ms) BY svc = resource.attributes.service.name, span = name
   | SORT slowest DESC
   | LIMIT 5
   ```
   On this project's data the top rows are the 30-second `connect` span from drill 1: the chaos-tooling bug recorded in `docs/incidents/2026-11-11-drill-1-connection-failed.md`.

## 7. Learning resources

Official Elastic documentation:
- [Get started with ES|QL](https://www.elastic.co/docs/explore-analyze/discover/try-esql): builds one query step by step on sample data. Best first stop.
- [ES|QL syntax](https://www.elastic.co/docs/reference/query-languages/esql/esql-syntax) and [processing commands](https://www.elastic.co/docs/reference/query-languages/esql/commands/processing-commands): the reference. Look things up here rather than memorising.
- [Explore fields and data with Discover](https://www.elastic.co/docs/explore-analyze/discover/discover-get-started): hands-on Discover tutorial using Kibana's sample data.
- [Learn data exploration and visualization with Kibana](https://www.elastic.co/docs/explore-analyze/kibana-data-exploration-learning-tutorial): Discover, then Lens charts, then dashboards, in order.
- [Kibana Discover search: KQL, Lucene and ES|QL](https://www.elastic.co/observability-labs/blog/kibana-discover-search-kql-lucene-esql): when to use which query language.

Practising without a cloud trial:
- [Elastic start-local](https://www.elastic.co/search-labs/tutorials/install-elasticsearch/start-local) runs Elasticsearch and Kibana on your own machine with Docker (Elastic's docs say it includes a one-month trial license with all features). It has not been run with this project; pointing the Collector at it should only need `ELASTIC_ENDPOINT` and `ELASTIC_API_KEY` changed in `.env`.
- Kibana's Discover has a "Describe your query in natural language" box. It is a reasonable way to get a first draft; always check what it produces.

Background reading this project is based on:
- [From Log Chaos to Real-Time Anomaly Detection with Elastic Streams](https://medium.com/@sdakwoji/from-log-chaos-to-real-time-anomaly-detection-with-elastic-streams-068ac23380cf)
