# Architecture Decision Records (ADRs)

An ADR captures a decision we made, why we made it, what we gave up by
making it, and the conditions under which we'd revisit it. Writing these
down matters here specifically because this project is full of deliberate
simplifications and deliberate landmines (like the undersized DB connection
pools) — six months from now it won't be obvious which of those were
intentional teaching choices and which were just bugs, unless it's written
down.

## When to add one

Add an ADR whenever a decision in this project meets any of these:
- It would look wrong or arbitrary to someone reading the code cold
- There were two or more real alternatives and we picked one
- We're deliberately doing something a production system wouldn't do (and
  future-us needs to remember why)

Don't write one for things with no real alternative (e.g. "we used Python's
`logging` module" doesn't need an ADR).

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-multi-service-topology.md) | Multi-service topology instead of a monolith | Accepted |
| [0002](0002-tech-stack-choice.md) | Python/FastAPI, Postgres, Redis as the stack | Accepted |
| [0003](0003-synchronous-request-handling.md) | Synchronous (not async) request handling | Accepted |
| [0004](0004-constrained-db-connection-pools.md) | Deliberately small, fixed-size DB connection pools | Accepted |
| [0005](0005-redis-cache-aside-pricing.md) | Redis cache-aside lookup for product pricing | Accepted |
| [0006](0006-frontend-co-hosted-on-gateway.md) | Frontend served as static files from api-gateway | Accepted |
| [0007](0007-zero-code-instrumentation.md) | Zero-code OTel instrumentation (`opentelemetry-instrument`) over manual SDK setup | Accepted |
| [0008](0008-collector-design.md) | Collector: contrib image, memory_limiter+batch, debug exporter, no container healthcheck | Accepted |
| [0009](0009-secrets-via-gitignored-env-file.md) | Elastic Cloud credentials via a gitignored `.env` file | Accepted |
| [0010](0010-direct-elasticsearch-endpoint.md) | Use the direct Elasticsearch endpoint, not Elastic's OTel-quickstart ingest gateway | Accepted |
| [0011](0011-cumulativetodelta-for-histograms.md) | `cumulativetodelta` processor to stop Elasticsearch from dropping histogram metrics | Accepted |
| [0012](0012-custom-ml-job-not-apm-toggle.md) | Custom ML anomaly job via direct API, not Kibana's built-in APM anomaly detection toggle | Accepted |
| [0013](0013-chaos-module-design.md) | Fault injection via genuine mechanisms (real pg_sleep, real bad port, real container stop), not faked error codes | Accepted |
| [0014](0014-fix-api-gateway-blocking-event-loop.md) | Fixed a real bug: api-gateway's `async def` endpoint blocking on a sync HTTP call | Accepted |
| [0015](0015-error-classification-on-logs.md) | Error classification lives on log records (`extra={"error.category": ...}`), not just span attributes | Accepted |
| [0016](0016-collector-side-dynamic-routing.md) | Collector-side dynamic routing into a dedicated hierarchy, not overriding Elastic's managed log template | Accepted |
| [0017](0017-explicit-keyword-mappings-for-ml.md) | Explicit keyword mappings for classifier fields -- `flattened` silently breaks ML datafeeds | Accepted |

## Template

```markdown
# ADR-NNNN: Title

Date: YYYY-MM-DD
Status: Accepted | Superseded by ADR-XXXX | Rejected

## Context
What problem were we solving? What constraints mattered?

## Decision
What we actually did.

## Alternatives considered
What else we could have done, and why we didn't.

## Consequences
What this costs us / what it buys us. Be honest about the downsides.

## Revisit when
Conditions under which this decision should be reconsidered (optional).
```
