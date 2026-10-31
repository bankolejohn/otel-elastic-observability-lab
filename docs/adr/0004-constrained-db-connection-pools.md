# ADR-0004: Deliberately small, fixed-size DB connection pools

Date: 2026-10-28
Status: Accepted

## Context

The reference Medium article's running example is a database-access layer
that produces categorized errors: `query_timeout`, `connection_failed`,
`pool_exhausted`, `unavailable`. To eventually reproduce that pattern with
*real* telemetry (Stage G) instead of synthetic bulk-inserted documents, the
app needs to be able to genuinely produce each of those failure categories
on demand.

## Decision

Both `orders-service` and `inventory-service` create their SQLAlchemy
engine with `pool_size=5, max_overflow=0, pool_timeout=5`:

```python
engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=0, pool_timeout=5)
```

`max_overflow=0` means the pool never grows beyond 5 connections — the 6th
concurrent request waits up to `pool_timeout` seconds, then fails with a
pool-timeout error. This is intentionally easy to exhaust with a small
number of concurrent/slow requests.

## Alternatives considered

- **A large or unbounded pool** (SQLAlchemy's default is larger). More
  realistic for a well-tuned production service, but then "pool exhausted"
  would require generating serious load to reproduce, which is out of
  scope for this project. Defeats the point of Stage G's chaos exercises.
- **Simulate pool exhaustion purely with a chaos flag** (e.g. a fake
  `/chaos/pool-exhausted` endpoint that just returns a canned error).
  Rejected because it would teach "what the error looks like" without
  "why it happens" — the whole point is to actually starve the pool, e.g.
  by holding connections open with an artificial `pg_sleep()`, and watch it
  happen.

## Consequences

- Under realistic concurrent use (several browser tabs placing orders at
  once), this app can genuinely show pool-timeout errors without any
  chaos tooling at all. That's a feature for Stage G, but worth remembering
  if Stage E/F exploration produces a confusing error during normal
  poking around — check concurrent request count before assuming something
  is broken.

## Revisit when

If pool exhaustion is firing unintentionally during normal single-user
testing in earlier stages, increase `pool_size` for that stage and note
it, rather than removing the constraint.
