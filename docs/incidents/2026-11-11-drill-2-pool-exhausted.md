# Incident drill 2 — orders failing under load (pool_exhausted)

**Date:** 2026-11-11
**Responder:** bankolejohn
**Drill runner:** Kiro (fault chosen at random by `scripts/run_blind_drill.sh`, sealed, not read until the responder committed)
**Status:** resolved (fault auto-reset after ~4 minutes)

> Blameless. The subject is the system and its signals.

## Timeline (UTC; Kibana shows local time, which is UTC+1)

| time | what happened |
|---|---|
| 10:42:51 | Fault injected (sealed). 6 concurrent orders every 3s for ~4 min. |
| 10:45:50 | Timestamp of the trace the responder cited (`6300adfc40bc61e955d8cdd09f9dd711`). |
| ~10:46:51 | Fault window ends; chaos mode auto-reset to `none` (verified). |
| after | Responder stated root cause: `pool_exhausted`. Answer revealed: `pool_exhausted`. |

## Scorecard
- **TTD:** not recorded.
- **TTR-diagnosis:** not recorded. (Still the one habit to build: write down the time at detection and at root cause.)
- **Correct?:** **Yes.** Committed to a single category, backed by a real trace ID.

## What actually happened
`pool_exhausted` chaos mode: each reservation holds its DB connection ~4s while inventory-service's pool has `pool_size=5, max_overflow=0, pool_timeout=3`. Under 6 concurrent orders every 3s, later requests waited the full 3s for a connection and failed.

## How it showed up in telemetry
Error counts in the drill window (10:42:50-10:47:30 UTC), `FROM logs.obs-shop.errors*`:

| category | service | count |
|---|---|---|
| query_timeout | orders-service | 195 |
| pool_exhausted | inventory-service | 183 |
| pool_exhausted | orders-service | 163 |

By category only: `pool_exhausted` = 346, `query_timeout` = 195. Grouping by service *and* category makes `query_timeout` the largest single row, which would mislead; group by category first.

Trace `6300adfc40bc61e955d8cdd09f9dd711` (started 10:45:50):
- `orders-service` `POST /orders`: Error, `pool_exhausted`, 3,076 ms (the caller's view; shallow).
- `inventory-service` `reserve_stock`: Error, `pool_exhausted`, 3,020 ms (the cause; deepest erroring span).
- `inventory-service` `connect`: Error, 3,013 ms, matching `pool_timeout=3`.

**Duration signature:** a `connect` span lasting about one timeout value means the request *waited* for a connection and gave up (pool exhaustion). A refused connection (`connection_failed`) fails in milliseconds.

## What worked
- Counting by category named the right cause; the trace confirmed it.
- The corrected chaos tooling produced a clean signal this time (compare drill 1's 30s artifact).
- Error categories on both services let the trace show cause and symptom together.

## What was slow or misleading
- Times were again not recorded, so speed cannot be scored.
- The cited row was the shallow caller span. The category matched here, but the cause lives one level deeper (`reserve_stock`); cite the deepest erroring span.
- The `query_timeout` entries (195) are probably a knock-on effect of sustained exhaustion: a request that waits up to 3s for a connection and then holds it ~4s exceeds orders-service's 5s limit. Not confirmed with a specific trace.
- The same failure is logged by two services, so raw counts double-count one incident (183 vs 163).

## Action items
- [ ] Responder habit: record detection and root-cause timestamps.
- [ ] Dashboard (point 2): Errors panel should plot only `availability_pct` on a 0-100 axis with a 99 line; add the category breakdown panel.
- [ ] Point 4: check whether and when the Stage I volume alert fired during this drill.
- [ ] Next drill should be a fault that does *not* produce errors (`slow`), to practice using the Duration panel.
