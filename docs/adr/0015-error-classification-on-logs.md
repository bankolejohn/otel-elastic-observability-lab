# ADR-0015: Error classification lives on log records, not just span attributes

Date: 2026-10-31
Status: Accepted

## Context

Stage G tagged error spans with `error.category` (e.g.
`span.set_attribute("error.category", "pool_exhausted")`), but the
reference Medium article's whole pattern is log-centric: a classified
`error.category` keyword on log *documents*, routed by Elasticsearch
ingest pipelines. Spans and logs are different OTel signals, exported
and mapped differently -- having the category only on spans wouldn't be
enough to build the article's pattern on real data.

## Decision

Added `error.category` to the relevant `logger.error(...)` calls via
Python logging's `extra={}` parameter (e.g. `extra={"error.category":
"pool_exhausted"}`), in both inventory-service and orders-service. Also
promoted connection-error handling that Stage G deliberately left
*uncaught* (specifically, orders-service's `query_timeout` and
"inventory-service unreachable" cases) to classify and raise a proper
HTTP response instead of crashing unhandled -- see ADR note in
`services/orders-service/app/main.py` explaining this is a deliberate
evolution, not an undoing, of Stage G's design (Stage G wanted an
*unclassified* failure to practice blind diagnosis; Stage 2 wants a
*classified* one, on purpose, since sorting known categories is the
actual goal now).

Also added a shared `_classify_operational_error()` helper in
inventory-service that distinguishes `connection_failed` (message
contains "connection refused" -- our deliberate bad-port chaos mode)
from `unavailable` (anything else -- e.g. "server closed the connection
unexpectedly" or "could not translate host name", both observed for
real when actually stopping the Postgres container) by inspecting the
real driver error message, not by which code path produced it.

Classified 5xx responses from inventory-service now carry the category
in a structured JSON body (`detail: {"message": ..., "error_category":
...}`) instead of a plain string, so orders-service (and by extension
api-gateway) can read and re-classify on the real cause instead of
losing it -- directly fixing the "generic 500 masks everything" problem
Stage G documented in 3 of its 5 code-level chaos scenarios.

## Alternatives considered

- **Only classify on spans, enrich logs by joining against trace_id at
  query time.** Technically possible (ES|QL supports `LOOKUP JOIN`), but
  adds a join to every single query that wants to look at errors by
  category, where a flat field on the log document itself is free.
- **Classify purely by parsing the log message text at the Elasticsearch
  ingest-pipeline level** (closer to the article's own approach, which
  infers `error.category` from message content via `contains()` checks
  in a `set` processor). Rejected in favor of classifying in application
  code, which we can do because we're the ones writing the application --
  the article's approach is designed for cases where you can't change the
  producer. Classifying as close to the source as possible is strictly
  better when it's available.

## Consequences

- Confirmed directly: `error.category` is now a real, queryable
  attribute on real log documents in Elasticsearch (verified via
  `_search` before building anything on top of it -- see the Stage 2
  doc).
- A genuine, informative side effect found while testing: orders-service's
  own httpx timeout (5.0s) and inventory-service's `pool_timeout` (5.0s)
  are numerically identical, so a pool-exhaustion event can race and get
  classified as `query_timeout` instead, depending on which side's clock
  fires first. Left as-is and documented (see Stage 2 doc) rather than
  "fixed" by staggering the timeouts -- it's a genuine, realistic
  characteristic of the current configuration, not a classification bug.

## Revisit when

If the query_timeout/pool_exhausted race above ever needs to be resolved
for real (not just understood), stagger the timeout budgets deliberately
(caller timeout > callee timeout, with real margin) rather than tuning
them to coincidentally avoid the race.
