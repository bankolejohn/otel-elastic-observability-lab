# ADR-0018: Staggered the query_timeout/pool_exhausted timeout race deliberately

Date: 2026-11-01
Status: Accepted

## Context

ADR-0015 documented, but deliberately didn't fix, a real classification
race: orders-service's `httpx` timeout calling inventory-service's
`/reserve` (5.0s) and inventory-service's own SQLAlchemy `pool_timeout`
(5s) were numerically identical. During a `pool_exhausted` chaos burst,
whichever side's clock fired first decided whether a given failed
request was classified `query_timeout` or `pool_exhausted` -- a
coin-flip, not a deliberate distinction. Left as a documented finding
through Stage 2, revisited now as a standalone fix.

## Decision

- inventory-service's connection pool: `pool_timeout` lowered from `5` to
  `3` seconds.
- The `pool_exhausted` chaos mode's connection-hold time raised from
  `pg_sleep(3)` to `pg_sleep(4)`, so a queued waiter's wait reliably
  exceeds the new 3s `pool_timeout` instead of narrowly avoiding it.
- orders-service's `httpx` timeout to inventory-service: left at `5.0`s,
  unchanged -- now a full 2 seconds larger than inventory-service's own
  timeout, a real margin instead of a coincidence.

The general rule this follows: a caller's timeout budget for a
downstream call should be meaningfully larger than that downstream's own
internal timeout for the same operation, so the downstream's own, more
specific error has time to surface and win, rather than the caller
giving up first and reporting something generic.

## Alternatives considered

- **Leave it as a documented race** (the original Stage 2 decision).
  Reasonable as a first pass -- the race itself was a genuine, valuable
  finding worth preserving in the docs regardless of whether it's later
  fixed. Revisited now because the user specifically wanted to spend
  time on this as a standalone exercise, not because leaving it
  undocumented-and-unfixed would have been wrong.
- **Raise orders-service's timeout instead of lowering inventory-service's.**
  Would also create margin, but inventory-service's pool_timeout is the
  one that should be shortest in the chain regardless (it's the
  innermost, most specific budget) -- lowering it is the more correct
  fix, not just the simplest one.

## Consequences

- Re-ran the exact same 20-concurrent-request burst that originally
  produced a mix of `504` (query_timeout) and `503` (pool_exhausted)
  responses. After this change: **zero 504s**, all 15 failures out of 20
  requests came back `503` with `error_category: "pool_exhausted"`,
  confirmed both via the HTTP responses and inventory-service's own logs.
- The `query_timeout` category can still occur for real (e.g. the
  dedicated `query_timeout` chaos mode's `pg_sleep(8)`, which still
  genuinely exceeds the caller's 5s budget) -- this fix only removes the
  *accidental* overlap with `pool_exhausted`, not the category itself.

## Revisit when

If `pool_timeout` or the caller's timeout ever change independently for
unrelated reasons, re-check that the margin between them is still real
before assuming classification stayed reliable.
