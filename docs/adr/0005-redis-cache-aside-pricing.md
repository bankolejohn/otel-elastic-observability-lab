# ADR-0005: Redis cache-aside lookup for product pricing

Date: 2026-10-28
Status: Accepted

## Context

We wanted a second dependency *type* beyond "another HTTP service" and
"a database" — specifically a cache, because caches fail differently
(stale data, cache stampede, cache-unavailable-but-system-still-works) and
that's a distinct, common production failure mode worth being able to
simulate and diagnose later.

## Decision

`orders-service` looks up a product's price via cache-aside:

1. Check Redis (`product:{id}`).
2. On a hit, use it.
3. On a miss (or if Redis itself errors), call `inventory-service` directly,
   then write the result back to Redis with a 30s TTL.

Redis errors are caught and treated as a cache miss, not a request
failure — `orders-service` degrades to calling inventory-service directly
rather than failing the whole order. See `get_product_cached()` in
`services/orders-service/app/main.py`.

## Alternatives considered

- **No cache at all, always call inventory-service.** Simpler, but removes
  an entire dependency type and failure mode (and a legitimate "slow
  downstream vs. down downstream vs. cache down" diagnosis exercise for
  Stage G).
- **Fail the request if Redis is unavailable.** More "correct" in some
  systems where the cache is load-bearing, but here the cache is purely an
  optimization — inventory-service is still the source of truth — so
  failing on cache errors would be modeling a dependency as more critical
  than it actually is.

## Consequences

- Orders-service has a code path that silently "hides" Redis being down
  (falls back to inventory-service without raising). This is correct
  behavior for a cache, but it also means a dead Redis instance looks
  identical from the outside (orders still succeed) — it only shows up as
  increased latency and 100% cache-miss load hitting inventory-service.
  That's deliberately realistic and will be a good diagnosis exercise in
  Stage G: "why did inventory-service's load suddenly double, with no
  errors anywhere?"

## Revisit when

N/A — this models a genuinely common pattern as-is.
