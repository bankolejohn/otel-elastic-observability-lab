# ADR-0003: Synchronous (not async) request handling

Date: 2026-10-28
Status: Accepted

## Context

FastAPI supports both `def` (run in a thread pool) and `async def` (run on
the event loop) endpoints. The HTTP client (`httpx`), the Redis client, and
the Postgres driver all have both sync and async variants.

## Decision

Every endpoint in every service is a plain `def`, using the synchronous
`httpx`, `redis-py`, and `psycopg2`/SQLAlchemy sync engine.

## Alternatives considered

- **`async def` everywhere with async drivers** (`httpx.AsyncClient`,
  `asyncpg`, `redis.asyncio`). More representative of how a performance-
  sensitive production FastAPI service is usually written, and async
  context propagation in OpenTelemetry is a real topic worth learning
  eventually. Not chosen for Stage A because mixing "learning distributed
  tracing" with "learning Python async" at the same time is more cognitive
  load than necessary right now.

## Consequences

- Simpler, more linear code: no `await`, no event loop gotchas.
- Under real concurrent load, sync endpoints running in FastAPI's thread
  pool will exhaust that thread pool before an equivalent async
  implementation would. This is actually convenient: the thread-pool limit
  plus the small fixed-size DB connection pool (ADR-0004) give us two
  independent, realistic ways to produce "service falls over under load"
  in Stage G, without needing a dedicated load-testing setup.

## Revisit when

If OTel context propagation across `async`/`await` boundaries becomes a
specific learning objective, convert one service to async as a focused
exercise rather than converting everything.
