# ADR-0013: Fault injection via genuine mechanisms, not faked error codes

Date: 2026-10-30
Status: Accepted

## Context

Stage G needed a way to reliably trigger the reference article's four
error categories (query_timeout, connection_failed, pool_exhausted,
unavailable) plus a generic "slow" case, on demand, for diagnosis
practice.

## Decision

`services/inventory-service/app/chaos.py` holds an in-memory,
process-local mode flag, toggled via `GET/POST /chaos`. Each mode
produces the failure for real rather than returning a canned status code:

- `slow` / `query_timeout`: an actual `SELECT pg_sleep(N)` runs inside the
  real transaction, on the real database.
- `connection_failed`: a real TCP connection attempt to a port nothing
  listens on (`chaos.get_bad_engine`), producing a genuine
  `psycopg2.OperationalError: Connection refused`.
- `pool_exhausted`: holds a real pooled connection open longer, so a
  *different*, concurrent request genuinely can't get one from the real
  pool (`pool_size=5, max_overflow=0`, ADR-0004) and gets a real
  `sqlalchemy.exc.TimeoutError`.
- `unavailable`: not a code-level mode at all -- simulated by actually
  stopping the `postgres` or `redis` container (`docker compose stop
  postgres`), a real, total outage.

Only `reserve_product` (the stock-reservation write) checks the chaos
mode -- not `get_product` (the price-lookup read). Placing an order
always calls `reserve_product`, regardless of Redis cache state; placing
an order only calls `get_product`'s inventory-service path on a cache
miss. Applying chaos there would make test runs inconsistent depending
on unrelated cache timing.

## Alternatives considered

- **Return canned error responses from a chaos flag, skipping any real
  DB/network interaction.** Would be simpler and faster to build, but
  would only test "does our error-handling code path run," not "what
  actually happens, end to end, when this really occurs" -- e.g. it
  would never have surfaced the query_timeout "phantom success" scenario
  (stock genuinely decremented after the caller gave up), which only
  exists because the underlying operation genuinely completes
  server-side regardless of what the caller does. A faked error would
  have hidden exactly the kind of inconsistency chaos testing exists to
  find.
- **Persist chaos mode somewhere durable (e.g. a file, Redis key).**
  Rejected -- in-memory means a container restart always resets to
  `none`, so there's no way to accidentally leave chaos mode on across a
  restart and get confused by it later.

## Consequences

- Testing `pool_exhausted` or `connection_failed` requires remembering to
  reset mode back to `none` afterward (`POST /chaos {"mode": "none"}`),
  or restart the container.
- `query_timeout` mode can leave the system in a genuinely inconsistent
  state on purpose (stock decremented, no matching order row) -- this is
  the point, not a cleanup bug; see the Stage G doc.

## Revisit when

If a future stage wants chaos mode controllable per-request (e.g. via a
header) rather than globally, to run normal and chaos traffic
side-by-side.
