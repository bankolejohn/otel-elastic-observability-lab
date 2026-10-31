# Stage G — Chaos engineering

Status: **Complete**
Related ADRs: [0013](../adr/0013-chaos-module-design.md), [0014](../adr/0014-fix-api-gateway-blocking-event-loop.md)

## What

A fault-injection mechanism in inventory-service (`/chaos`) that produces
five genuine failure modes on demand, plus real container-stop outages
for Postgres and Redis. Ran all six, captured real evidence for each via
Elasticsearch, and along the way found and fixed a real concurrency bug
in api-gateway that the original "deliberate landmines" from Stages A-D
were waiting for a chaos test to expose.

## Why

Every stage since A has planted something on purpose for this moment:
undersized DB pools (ADR-0004), synchronous endpoints (ADR-0003), Redis
as a non-critical cache (ADR-0005). Stage G is where those pay off —
simulate the failures the original project goal asked for (slow
responses, timeouts, dependency issues) and use the telemetry pipeline
built in Stages B-F to actually diagnose them, the same way a real
on-call engineer would.

## How it works

See ADR-0013 for the full design. Summary: `GET/POST
http://localhost:8002/chaos` with `{"mode": "..."}`, where mode is one of
`none`, `slow`, `query_timeout`, `connection_failed`, `pool_exhausted`.
`unavailable` isn't a code mode — it's `docker compose stop postgres` (or
`redis`), a real outage.

## The six scenarios, with real evidence

### 1. `slow` — succeeds, just slowly

`SELECT pg_sleep(2)` runs inside the real reservation transaction.
Placed an order: **2.198s total**, HTTP 200. The `reserve_stock` span's
own `duration` field: `2025641863` (nanoseconds = 2.03s), with
`chaos.mode: "slow"` right there as a span attribute. Nothing failed;
this mode exists to prove the *metric/trace* side shows a slowdown
clearly, not to produce an error.

### 2. `query_timeout` — a phantom success

`SELECT pg_sleep(8)` exceeds orders-service's 5s `httpx` timeout to
inventory-service. The caller (api-gateway, by way of orders-service)
got a **500** after 5.89s. But inventory-service's transaction **kept
running** and committed 3 seconds later. Confirmed directly:

- Product 1's stock dropped 29 → 28.
- No new order row was created (orders-service never reached its own
  `INSERT` — the exception from the timed-out call stopped it first).
- In Elasticsearch, one `trace_id` shows both halves of the story at
  once: orders-service's client span for the call has
  `status: Error, message: "ReadTimeout: timed out"` at 5.05s, while
  inventory-service's own `reserve_stock` span (same trace, different
  service) shows `inventory.result: "reserved"`, no error, duration
  8.01s. Two services, two completely different opinions about whether
  the same operation succeeded — both correct, from where they're
  standing.

This is a real, common distributed-systems trap, not a contrived one:
whenever a caller times out a request to something that keeps running
independently, this exact disagreement is possible.

### 3. `connection_failed` — the trace knows more than the response does

Chaos mode points inventory-service at a port nothing listens on.
inventory-service correctly caught the resulting
`psycopg2.OperationalError` and returned a clean `503 Database
connection failed`. But orders-service's `reserve_resp.raise_for_status()`
turns *any* non-2xx into an unhandled exception (no special case for
503), which becomes a generic `500`. api-gateway then tries to parse that
500's body as JSON (it's plain text), throws again, and returns its own
generic 500. **The caller ends up with zero information** about what
actually went wrong, three services later.

The trace tells the real story: the `reserve_stock` span carries
`error.category: "connection_failed"` and `status.message: "HTTPException:
503: Database connection failed"`, and the nested `connect` span one
level deeper has the full, real driver error: `connection to server at
"postgres" (172.20.0.3), port 5499 failed: Connection refused`. This is
deliberately left as-is, not "fixed" by making orders-service/api-gateway
smarter about forwarding error details — real systems very often have
exactly this thin error propagation, and "the HTTP status doesn't tell
you why, the trace does" is the actual skill being practiced here.

### 4. `pool_exhausted` — and a real bug it exposed

First attempt: fired 10, then 20, "concurrent" requests. Got **zero**
pool-timeout failures — just steadily increasing total latency (3.4s up
to 62.4s for the last request), evenly spaced at almost exactly the
chaos-induced hold time apart. That evenness was the tell: genuinely
parallel requests wouldn't queue that cleanly. Bisected by calling each
service directly:

- inventory-service directly, 2 different products: ran in parallel (~3.0s both).
- orders-service directly, 2 different products: ran in parallel (~3.2s both).
- api-gateway, 2 different products: **did not** run in parallel — one
  request waited for the other to fully finish (3.1s, then 6.2s).

Root cause: `api-gateway`'s `/api/orders` endpoint was `async def` but
called the *synchronous* `httpx.post()` inside it — a blocking call
inside an async function blocks FastAPI's entire event loop, serializing
every concurrent request regardless of which product or which
downstream pool was involved. Fixed in ADR-0014 (converted to a plain
sync `def`, matching every other endpoint in the codebase). Re-verified
the fix with the same 2-request test: both now complete in parallel
(~3.2-3.3s each).

With the real bottleneck gone, re-ran the pool test: 20 concurrent
requests against a pool of 5 produced **5 successes around 3.3-3.5s**
and **15 failures around 5.5-6.0s** (right at the 5s `pool_timeout`).
inventory-service's logs show the exact, real error: `QueuePool limit of
size 5 overflow 0 reached, connection timed out, timeout 5.00`. The
HTTP responses were (again) a generic 500 by the time they reached the
caller — same cascading-error-detail issue as scenario 3.

### 5. `unavailable` (Postgres) — total outage, and a recovery gotcha

`docker compose stop postgres`, then placed an order: failed in 0.137s
with `server closed the connection unexpectedly` (a pooled connection
that was alive when checked out, dead by the time it was used — a
different error shape than `connection_failed`'s "never connected at
all," worth telling apart). After `docker compose start postgres` and an
8s wait, the **first** order attempt still failed with the same error —
a stale connection from before the restart, still sitting in the pool.
The **second** attempt succeeded. SQLAlchemy doesn't validate pooled
connections by default (no `pool_pre_ping`); the first failure is what
evicts the bad one. Documented as a real, found characteristic — not
patched, since fixing it isn't necessary to complete this exercise and
`pool_pre_ping` is a one-line, well-understood fix if this project ever
needs it for real.

### 6. `unavailable` (Redis) — ADR-0005's prediction, confirmed

`docker compose stop redis`, then placed orders: **zero errors**.
Logs show exactly the designed fallback: `WARNING: Redis unavailable,
falling back to inventory-service`, cache miss handling kicks in, the
order completes normally (409 in this case, correctly due to actual
stock, not Redis). Exactly as ADR-0005 predicted when Redis was added
back in Stage A: a dead cache is invisible from the outside here, and
the only symptom is that inventory-service now takes 100% of the lookup
load instead of a fraction of it — a symptom you'd only catch by
watching load/latency, never by watching for errors.

## How to reproduce

```bash
# slow / query_timeout / connection_failed / pool_exhausted
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode": "query_timeout"}'
curl -X POST http://localhost:8000/api/orders -H "Content-Type: application/json" -d '{"product_id": 1, "quantity": 1}'
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode": "none"}'   # reset

# pool_exhausted needs real concurrency
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode": "pool_exhausted"}'
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "status=%{http_code} time=%{time_total}\n" \
    -X POST http://localhost:8000/api/orders -H "Content-Type: application/json" \
    -d "{\"product_id\": $(( (i % 2) + 1 )), \"quantity\": 1}" &
done
wait
curl -X POST http://localhost:8002/chaos -H "Content-Type: application/json" -d '{"mode": "none"}'

# total outages
docker compose stop postgres   # or redis
curl -X POST http://localhost:8000/api/orders -H "Content-Type: application/json" -d '{"product_id": 1, "quantity": 1}'
docker compose start postgres
```

## Troubleshooting log

Most of this stage's real content *is* its own troubleshooting log —
each scenario above documents exactly what was expected, what actually
happened, and (for scenario 4) a genuine bug found and fixed along the
way. The meta-lesson across all six: **the HTTP status code the caller
sees is frequently not trustworthy evidence of what happened** — it was
wrong or misleading in 4 of 6 scenarios (query_timeout, connection_failed,
pool_exhausted all degraded to generic 500s; Redis-down looked identical
to a normal 409). The trace, and specifically the deepest span in the
chain, was the only reliable source of truth every time.

## What's next

This completes the originally-scoped roadmap (Stages A-G). Next is
**Stage 2**: applying the Elastic Streams / ML pattern from the reference
Medium article on top of everything built here — reroute pipelines,
child streams by `error.category` (already present as a span attribute
on every chaos scenario above, ready to be classified on), and
production-grade anomaly detection tuned with everything learned in
Stage F about needing a real baseline.
