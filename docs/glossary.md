# Glossary

Terms get added here as they become relevant, stage by stage, each tied
back to where they actually show up in this project. If a term feels
abstract, the "in this project" line is the thing to re-read.

## Stage A terms

**Service boundary**
A line between two pieces of software that only talk to each other over
the network (HTTP, a DB protocol, etc.), as opposed to a function call in
the same process. Only service boundaries produce distributed traces —
calling a Python function doesn't.
*In this project:* `api-gateway → orders-service`, `orders-service →
inventory-service`, and both services' calls to `postgres`/`redis` are all
service boundaries. Internal function calls within one service (e.g.
`get_product_cached()`) are not, until Stage B adds manual spans inside
them.

**Dependency**
Anything a service calls that it needs (fully or partly) to do its job.
Dependencies are the things that fail independently of the service calling
them, which is exactly why they matter for diagnosis.
*In this project:* orders-service has three dependencies: Redis (optional —
it degrades gracefully if Redis is down), inventory-service (required), and
Postgres (required).

**Connection pool**
A fixed set of reusable database connections a service keeps open, instead
of opening a new one per request (opening a connection is slow). A pool has
a maximum size; if every connection is in use, the next request waits
(`pool_timeout`) and then fails if nothing frees up in time.
*In this project:* see ADR-0004 — pools are deliberately small
(`pool_size=5, max_overflow=0`) so we can reproduce "pool exhausted" for
real in Stage G, not just simulate the error message.

**Cache-aside pattern**
A caching strategy where the application (not the cache or the database)
is responsible for the logic: check the cache first, fall through to the
real source on a miss, then write the result back to the cache. Contrast
with a cache that sits transparently in front of the database and handles
misses itself.
*In this project:* `get_product_cached()` in orders-service: check Redis →
on miss, call inventory-service → write result to Redis with a 30s TTL.
See ADR-0005.

**Graceful degradation**
A dependency failing reduces functionality or performance, but doesn't take
the whole request down, because the calling code explicitly handles that
failure as a distinct case.
*In this project:* if Redis raises `redis.RedisError`, `orders-service`
catches it and falls through to calling inventory-service directly — the
order still succeeds, just slower and with more load on inventory-service.

## Stage B terms

**Span**
One timed unit of work, with a name, a start/end time, a status, and a set
of key-value attributes. A span can be created automatically (by
instrumentation watching a library) or manually (by application code).
*In this project:* `opentelemetry-instrumentation-fastapi` creates a span
for every inbound HTTP request automatically; `get_product_cached` in
orders-service and `reserve_stock` in inventory-service are hand-written
spans we added ourselves, visible as `"kind": "SpanKind.INTERNAL"` in the
console output.

**Trace**
A tree of spans that all share one `trace_id`, representing everything
that happened to serve one logical operation — potentially across many
services. The tree shape comes from each span's `parent_id`.
*In this project:* placing one order produces a trace with spans from
api-gateway, orders-service, and inventory-service all sharing the same
`trace_id` — confirmed on 2026-10-28 by grepping each service's console
output for `77457be0dfecd20702cbadf7bd9b0397` and finding it in all three.

**Trace context propagation**
How a `trace_id`/`span_id` pair travels from a calling service to a
called service, so the callee's spans join the caller's trace instead of
starting a new one. Done via a `traceparent` HTTP header (W3C Trace
Context spec), injected automatically by client-side HTTP instrumentation
and read automatically by server-side instrumentation.
*In this project:* `opentelemetry-instrumentation-httpx` injects
`traceparent` on every outbound call (api-gateway→orders-service,
orders-service→inventory-service); `opentelemetry-instrumentation-fastapi`
reads it on the receiving end. No code we wrote does this directly.

**Resource attributes**
Metadata describing *what produced* a piece of telemetry (as opposed to
span attributes, which describe the specific operation) — which service,
which environment, which SDK version. Attached once per process, not per
span.
*In this project:* `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` in
`docker-compose.yml` set `service.name`, `service.namespace`, and
`deployment.environment` on every span/metric/log each service produces.

**Zero-code (automatic) instrumentation vs. manual instrumentation**
Zero-code: a library is patched at process startup to emit telemetry
without the application code knowing about it. Manual: application code
explicitly creates spans/metrics using the OTel API. See ADR-0007 for why
this project uses both together.
*In this project:* `opentelemetry-instrument uvicorn ...` (the Dockerfile
`CMD`) is zero-code; `tracer.start_as_current_span(...)` calls in
`main.py` are manual.

**Log-trace correlation**
Attaching the currently-active `trace_id`/`span_id` to a log line, so a
specific log message can be traced back to the exact request/operation
that produced it, and vice versa.
*In this project:* `OTEL_PYTHON_LOG_CORRELATION=true` makes every
`logger.info(...)` call print `trace_id=... span_id=...` in the log line
— see the troubleshooting note in `docs/stages/stage-b-opentelemetry-instrumentation.md`
for why our own `logging.basicConfig()` calls don't override this.

**Metric instrument (counter, histogram, ...)**
A typed way of recording a measurement. A **counter** only goes up (e.g.
"number of orders created"); a **histogram** records a distribution of
values (e.g. request duration) and is what powers `http.server.duration`.
*In this project:* `orders.created` and `orders.cache_lookup` are
hand-written counters; `http.server.duration` and
`db.client.connections.usage` are automatic instruments created by the
FastAPI and SQLAlchemy instrumentation packages respectively.

## Stage C terms

**OpenTelemetry Collector**
A standalone process that sits between applications and telemetry
backends: it receives telemetry, optionally transforms it, and exports it
onward — so applications only need to know about one destination
(the Collector), not every backend that might ever consume their data.
*In this project:* the `otel-collector` service in `docker-compose.yml`,
running `otel/opentelemetry-collector-contrib:0.153.0`.

**Receiver**
The part of a Collector pipeline that accepts incoming telemetry over some
protocol.
*In this project:* the `otlp` receiver, listening for OTLP over gRPC
(port 4317) and HTTP (port 4318) — see `otel-collector/config.yaml`.

**Processor**
A pipeline stage that does something to telemetry between receiving it
and exporting it. Order matters — processors run in the sequence listed.
Easy misconception: a processor doesn't necessarily look at an item's
*content*. `memory_limiter` and `batch` (the two we use) are purely
operational/mechanical — they manage resource usage and timing/volume,
not what's inside a span/log/metric. Content-aware processors also exist
(`attributes` to add/modify fields, `filter` to drop matching items,
`routing` to send different items to different exporters) — we're just
not using any of those yet.
*In this project:* `memory_limiter` (checks the Collector's own memory
every second; refuses new data if it's too high) runs before `batch`
(accumulates items until 1024 of them arrive or 5 seconds pass, then
exports them as one batch) — see ADR-0008 for why both are included even
at this project's tiny scale. Don't confuse this with Elasticsearch's
*ingest pipeline* (coming in Stage 2), which genuinely does route
documents based on their content (e.g. `error.category`) — a third,
unrelated meaning of "pipeline" alongside this one and CI/CD's.

**Exporter**
The part of a Collector pipeline that sends telemetry onward to a
specific destination/format.
*In this project:* `debug`, which prints everything it receives to the
Collector's own stdout — a deliberate placeholder for Stage D's
`elasticsearch` exporter.

**Pipeline**
A named wiring of `receivers → processors → exporters` for one telemetry
signal type (traces, metrics, or logs). A Collector can run multiple
pipelines. **Not the same kind of thing as a CI/CD pipeline**, despite the
shared name: a CI/CD pipeline is triggered by an event and runs once,
start to finish, over one artifact. A Collector pipeline never finishes —
it's a standing, continuously-running conveyor belt that every item of
telemetry flows through independently, for as long as the Collector
process is up. There's no "pipeline run" to point at and call successful
or failed, the way there is for a CI/CD job.
*In this project:* three pipelines in `otel-collector/config.yaml`
(`traces`, `metrics`, `logs`), all currently wired the same way. Note that
listing the same processor name (e.g. `batch`) in two different pipelines
creates two independent instances of it, one per pipeline, each with its
own internal state — reusing a name doesn't mean reusing a running
instance. Receivers and exporters, by contrast, *are* shared if the same
one is referenced by multiple pipelines.

**OTLP (OpenTelemetry Protocol)**
The wire protocol OpenTelemetry SDKs and Collectors use to exchange
telemetry, over either gRPC (port 4317 by convention) or HTTP/protobuf
(port 4318 by convention).
*In this project:* every app service's `OTEL_EXPORTER_OTLP_ENDPOINT`
points at `http://otel-collector:4317` using the gRPC protocol — see
`OTEL_EXPORTER_OTLP_PROTOCOL: grpc` in the `x-otel-env` block.

## Stage D terms

**Elastic Cloud deployment vs. serverless project**
Two ways Elastic Cloud offers a running Elasticsearch+Kibana: a classic
**deployment** (you can see/configure more infrastructure detail, e.g.
node counts) or a newer **serverless project** (fully managed, no cluster
sizing exposed). Both expose the same Cloud ID / API key / Elasticsearch
endpoint concepts underneath, so nothing about the exporter config
differs between them.
*In this project:* the trial account created a serverless project
(confirmed by `"build_flavor": "serverless"` in the root Elasticsearch
response).

**Cloud ID vs. Elasticsearch endpoint**
Two different ways to tell a client where to connect: a **Cloud ID** is
an opaque encoded string (`name:base64...`) that some Elastic client
libraries can decode into a URL themselves; an **Elasticsearch endpoint**
is just the plain HTTPS URL. The `elasticsearchexporter` accepts either.
*In this project:* ended up using the plain endpoint URL (from Kibana's
Console settings), not a Cloud ID — see ADR-0010.

**API key (encoded format)**
A single base64-ish string that encodes both an id and a secret together,
used as `Authorization: ApiKey <value>`. Different from the separate
`id`/`api_key` pair Elasticsearch's API also supports — the exporter
config here wants the combined "encoded" form.

**Managed ingest gateway**
A write-only intake service some Elastic onboarding flows hand you an
endpoint for — it accepts data (and can return real validation feedback
about it) without necessarily making that data queryable at the endpoint
you were given. Identifiable by a non-cluster-like `name` in its root
response (e.g. `"managed-inputs"`) and `_search`/`_cat/*` returning plain
404s instead of Elasticsearch-shaped errors.
*In this project:* what Elastic's "Add Observability data → OpenTelemetry"
quickstart screen handed out — see ADR-0010 for how this was diagnosed
and why the direct endpoint was used instead.

**Data stream naming (OTel-native mapping mode)**
With the Elasticsearch exporter's default mapping mode (`otel`), data
lands in data streams named `<type>-<dataset>.otel-<namespace>`, e.g.
`logs-generic.otel-default`, `traces-generic.otel-default`,
`metrics-generic.otel-default` — `generic`/`default` because nothing in
this project has set a more specific `data_stream.dataset`/`namespace`
yet (that becomes relevant in Stage 2, where the Medium article's
per-category child streams are a similar idea applied deliberately).

**Cumulative vs. delta temporality (metrics)**
Two ways a counter/histogram metric can report its value over time:
**cumulative** reports the running total since the process started (each
data point includes everything before it); **delta** reports only what
happened since the last report. OTel SDKs default to cumulative;
Elasticsearch's exporter can only store histograms as delta.
*In this project:* the `cumulativetodelta` processor converts before
export — see ADR-0011 for the data-loss bug this fixed.

## Stage F terms

**Anomaly detection job**
A trained statistical model that learns what "normal" looks like for a
chosen measurement over time, then scores new data by how far it departs
from that learned normal. Needs enough history of real (non-empty) data
points to build a meaningful model — a handful of observations isn't
enough, regardless of how extreme a new value is.
*In this project:* `service_request_spikes`, created via
`PUT _ml/anomaly_detectors/service_request_spikes`, with one detector:
`high_count` partitioned by `resource.attributes.service.name`.

**Datafeed**
The thing that actually pulls data from an index/data stream into an
anomaly detection job, on a schedule. A job without a (started) datafeed
never sees any data.
*In this project:* `datafeed-service_request_spikes`, reading from
`traces-generic.otel-default`.

**Bucket span**
The time window an anomaly detection job groups data into before scoring
it — one score per bucket, per partition. Shorter = faster feedback but
less data per bucket to average over; longer = smoother but slower to
react.
*In this project:* `1m`, chosen deliberately short so buckets would
accumulate fast enough to observe anything at all within one working
session, rather than the article's `15m` (tuned for a real production
log volume we don't have).

**query_delay**
How long a datafeed waits after a bucket's time window closes before
analyzing it, to give slightly-late data a chance to arrive. Must exceed
your real shipping lag, or the job scores a bucket before the data for it
has actually landed — see the reference article's "Lesson 1" for what
happens when this is set too short (real spikes scored as ~0 because the
job looked before the data arrived).
*In this project:* `30s`.

**Influencer**
A field the job additionally reports on when something is flagged
anomalous — "which entity should I blame" alongside the raw score.
*In this project:* `resource.attributes.service.name`.

**record_score / anomaly_score**
The 0-100 "how unusual was this" number a job assigns. `anomaly_score`
is per time bucket; `record_score` is per individual anomaly record
within a bucket (a bucket can have multiple detectors/partitions, each
producing its own record).
*In this project:* every bucket scored `0.0`, including one with **901**
events in a single 1-minute window (versus 95/72/29/9 in the only other
four non-empty buckets out of 1119 total) — the job's entire history has
so few real observations that it can't yet distinguish "unusual" from
"within the (very wide, barely-sampled) range I've seen so far." This is
the practical version of the reference article's "Lesson 2" (a model
trained on bursty data learns bursts as normal) compounded by having
almost no data at all to train on — a real, firsthand instance of both
problems, not a simulated one. See
`docs/stages/stage-f-anomaly-detection.md`.

## Stage G terms

**Chaos engineering**
Deliberately injecting real failures into a running system to find out
how it actually behaves under them, rather than how you assume it
behaves. "Real" matters: a faked error response only tests your
error-handling code path, not what genuinely happens end to end.
*In this project:* `services/inventory-service/app/chaos.py` — see
ADR-0013 for why every mode produces a genuine failure (real
`pg_sleep`, real connection refusal, real pool exhaustion, real
container stop) instead of a canned status code.

**Caller/callee disagreement (a "phantom success")**
A distributed-systems failure mode where a caller times out and reports
failure, while the callee it gave up on keeps running and actually
succeeds afterward — so the system ends up in a state the caller never
finds out about.
*In this project:* `query_timeout` chaos mode. orders-service's 5s
`httpx` timeout gave up and returned a 500, but inventory-service's
`pg_sleep(8)` + reservation **committed anyway** 3 seconds later — stock
was decremented with no corresponding order row ever created. Confirmed
directly: `inventory.result: "reserved"` in the trace, right next to
`status: Error` on the caller's own span for the same `trace_id`.

**Event loop blocking**
In an async framework (FastAPI/Starlette/asyncio), an `async def`
function that calls a *synchronous*, blocking operation (like the plain
`httpx.post()`, not `httpx.AsyncClient`) blocks the entire event
loop — not just that one request, every concurrent request the process
is handling — for the duration of that call.
*In this project:* a real, unintentional bug found via chaos testing,
not a deliberate landmine — see ADR-0014. Diagnosed by bisection: calling
each service directly, one hop at a time, to find exactly where
concurrent requests stopped running in parallel.

**Stale pooled connection**
A connection sitting in a pool that *looks* fine to the pool (it's just
an object reference) but whose underlying TCP connection has actually
died (e.g. because the database restarted). Without a pool configured to
test connections before handing them out (e.g. `pool_pre_ping`), the
first request to get a stale one fails; only after the pool discards it
does the next request get a fresh, working connection.
*In this project:* observed directly after restarting Postgres mid-chaos
test — the first order placed after Postgres came back still failed
(`server closed the connection unexpectedly`), the second succeeded.
Documented as a real characteristic found, not fixed (see
`docs/stages/stage-g-chaos-engineering.md`).

**Diagnosis by bisection**
Finding which hop in a multi-service chain is responsible for an
observed symptom by testing each hop directly, one at a time, narrowing
down from "somewhere in here" to "exactly here" — the same technique as
a binary search or `git bisect`, applied to a request path instead of a
commit history.
*In this project:* this is literally how ADR-0014's bug was found: call
inventory-service directly (fine) → call orders-service directly (fine)
→ call api-gateway directly (broken) → read the one file left.

## Stage 2 terms (the Medium article, applied)

**Elastic Streams (the pattern, not necessarily the managed feature)**
A hierarchy of data streams — one parent acting as both entry point and
catch-all, several children each holding one category of a classified
field — built from plain data streams, index templates, and an ingest
pipeline, rather than Kibana's point-and-click "Streams" UI feature. The
article offers both; this project builds the plain version, same as the
article's own "Build it yourself" section does.
*In this project:* `logs.obs-shop.errors` (parent) and
`logs.obs-shop.errors.{query_timeout,connection_failed,pool_exhausted,unavailable}`
(children).

**Reroute pipeline**
An Elasticsearch **ingest pipeline** (see the Collector-vs-ingest-pipeline
distinction from Stage C's glossary entry) containing one or more
`reroute` processors, each conditionally sending a document to a
different destination index/data stream instead of the one it was
addressed to. No `else`/default case is the deliberate safety feature:
unmatched documents simply aren't rerouted, and stay exactly where they
were sent — the parent.
*In this project:* `logs.obs-shop.errors@reroutes`, set as the parent
data stream's `index.default_pipeline`.

**Catch-all stream**
The parent stream in a Streams hierarchy, which also absorbs anything
that didn't match any child's routing condition — so a new, as-yet-
unclassified failure category is never silently dropped or misfiled,
just left searchable in one place until someone writes a rule for it.
*In this project:* confirmed directly by sending a test document with
`error.category: "something_never_seen_before"` — it landed in
`logs.obs-shop.errors` itself (its own backing index), not any child,
and not an error.

**`_field_caps` (field capabilities)**
An Elasticsearch API (`GET <index>/_field_caps?fields=...`) that reports
whether a field is actually aggregatable/filterable as its own field —
distinct from whether it's merely visible inside a document in
`_search` results. A field can appear present and healthy in every
search result while being invisible to `_field_caps`, if it's nested
inside a `flattened`-typed object rather than mapped individually.
*In this project:* this exact gap broke the ML datafeed (`attributes.error.category`
had no mappings per `_field_caps`, despite working fine in plain
`_search` term queries) — see ADR-0017. The article calls this out by
name as its own "mapping gotcha" lesson; this project reproduced it
firsthand rather than reading about it.

**`flattened` field type**
An Elasticsearch field type for an object with arbitrary, varied,
unpredictable sub-keys (like a generic attributes map) — stores the
whole object as one field, supports exact-match queries on sub-paths,
but doesn't expose those sub-paths as individually aggregatable fields.
The right tool for "arbitrary extra data," the wrong tool for "the one
specific field I need to run an ML job or alert on."
*In this project:* used for the error-streams component template's
catch-all attribute fields, specifically *not* used for
`error.category`/`service.name` once their need for aggregation became
clear — see ADR-0017.

## Stage H terms (browser instrumentation, a post-completion extension)

**CDN-as-bundler (esm.sh)**
A service that resolves npm package names into browser-ready ES modules
on demand over HTTP, so `import` statements in plain `<script
type="module">` code can reference npm packages directly, with no local
install or build step. Handles transitive dependencies automatically --
but, left to its own defaults, may resolve the *same* shared dependency
to *different* versions/instances for different top-level packages,
which matters a lot for libraries (like OpenTelemetry's API) that rely
on one shared global registry.
*In this project:* `services/api-gateway/static/otel-web.js` imports
everything this way; see ADR-0019 for the real problem this caused and
the fix (`?deps=` pinning).

**Global registry (singleton) pattern**
A design where a library expects exactly one shared instance of itself
to exist process-wide, reached via module-level functions
(`setGlobalTracerProvider`/`trace.getTracer()`) rather than passed
explicitly between every caller and callee. Works perfectly inside one
bundled application; breaks silently if two different copies of the same
module end up loaded side by side, because "global" then means two
different things depending on which copy of the code asks.
*In this project:* `@opentelemetry/api`'s trace/propagation/context
registry — exactly what broke when esm.sh handed different packages
different copies of it (ADR-0019, bug #3).

**Diagnostic (silent-by-default) logging**
A library's own internal logger, used for "this isn't working and here's
why" messages, deliberately set to do nothing by default so a correctly-
functioning production system isn't flooded with noise. The tradeoff:
when something *is* wrong, the default silence looks identical to
"nothing is wrong, there's just nothing to report."
*In this project:* `@opentelemetry/api`'s `diag` object. Its default
no-op logger is exactly what made bug #3 (the registry mismatch) produce
zero visible errors anywhere — enabling `DiagConsoleLogger` was the only
way to see what was actually failing.

**Dependency pinning across independently-resolved CDN imports**
Forcing two or more separately-imported packages to resolve one specific
shared dependency to the exact same version/URL, instead of letting each
resolve it independently (which can silently diverge). esm.sh's
mechanism for this is a `?deps=pkg@version` query parameter on the
*importing* package's URL.
*In this project:* applied narrowly, only to the packages that actually
touch OpenTelemetry's global registry — applying it universally broke a
*different* package's unrelated dependency resolution (ADR-0019, bug #4),
which is itself the core lesson: pin precisely what needs pinning, not
everything that happens to share a name.

## Coming in later stages

(none — the originally-scoped roadmap is complete; this and further
entries belong to post-completion extensions, tracked as Stage H onward
in `README.md`)
