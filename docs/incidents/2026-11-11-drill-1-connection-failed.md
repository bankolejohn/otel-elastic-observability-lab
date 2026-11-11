# Incident drill 1 — orders failing (connection_failed)

**Date:** 2026-11-11
**Responder:** bankolejohn
**Drill runner:** Kiro (fault chosen at random by `scripts/run_blind_drill.sh`, sealed, not read until the responder committed)
**Status:** resolved (fault auto-reset after ~4 minutes)

> Blameless. The subject is the system and its signals.

## Timeline (UTC; Kibana shows local time, which is UTC+1)

| time | what happened |
|---|---|
| 10:14:32 | Fault injected (sealed). 6 concurrent orders every 3s for ~4 min. |
| ~10:18:30 | Fault window ends; chaos mode auto-reset to `none` (verified). |
| 10:18:26-38 | Rows the responder was looking at in `logs.obs-shop.errors*` (shown as 11:18 local). These are the *tail* of the incident. |
| after | Responder reported: "poolexhausted, db error connection failed". Answer revealed: `connection_failed`. |

## Scorecard
- **TTD:** not recorded. The dashboard clearly showed the incident (the `bad` bars and the dip in the Errors panel), so detection worked. The responder did not note a timestamp.
- **TTR-diagnosis:** not recorded, same reason.
- **Correct?:** **Partially.** The right cause was named, but alongside a wrong one, and the responder did not separate cause from symptom.

## What actually happened
`connection_failed` chaos mode: inventory-service pointed its DB engine at a port nothing listens on. Under concurrent load this cascaded.

## How it showed up in telemetry
Error counts inside the drill window (10:14:30-10:19:00 UTC), from `FROM logs.obs-shop.errors*`:

| category | service | count |
|---|---|---|
| connection_failed | inventory-service | 465 |
| connection_failed | orders-service | 342 |
| query_timeout | orders-service | 149 |
| pool_exhausted | inventory-service | 22 |

`connection_failed` = 807 of 978 errors (83%). All-time counts (the mixed view the responder likely saw) were 847 / 165 / 62 across connection_failed / query_timeout / pool_exhausted, polluted by earlier test days.

One trace (`38f3ca016ff766deeda1ae36a2a3f8ea`, started 10:17:56) showed the cascade: `orders-service` gave up at 5.1s (`query_timeout`) while `inventory-service`'s `reserve_stock` span ran 30s and ended `pool_exhausted`, with its `connect` span stuck for 30.01s. Different services labelled the same request differently, because each reports its own vantage point.

## What worked
- The RED dashboard made the incident obvious (bad bars, availability dip).
- The error-category stream gave the right vocabulary immediately.
- The trace plus `error.category` span attributes made cause vs. symptom readable.

## What was slow or misleading
- **The responder diagnosed from the last few rows, not from counts over the incident window.** The tail of a cascade shows symptoms; the bulk shows the cause. Always sort by count over the *whole* window first.
- **Two secondary categories (`query_timeout`, `pool_exhausted`) are an artifact of my chaos code, not a realistic effect.** `chaos.get_bad_engine()` builds its throwaway engine with `pool_size=1` and no `pool_timeout`, so SQLAlchemy's default of 30s applies; under concurrency, requests queue for that single slot for up to 30s. I have not confirmed this with the QueuePool log line for this trace, but it matches the 30.01s `connect` span and the code. It muddied the drill.
- The Errors panel plots `total`, `bad` and `availability_pct` on one axis. Availability (0-100) is nearly invisible next to totals above 100, so the SLO line cannot be read.
- Unfamiliarity with pivoting from a `trace_id` to the full trace.

## Action items
- [ ] Dashboard (point 2): the Errors panel should plot only `availability_pct`, on a 0-100 axis with a line at 99.
- [ ] Dashboard (point 2): add the error-category breakdown panel and set its time range to the incident window.
- [ ] Chaos tooling: give the bad engine in `chaos.py` a short `pool_timeout` so `connection_failed` stays a clean `connection_failed`.
- [ ] Responder habit: record a timestamp at detection and at root cause; start every diagnosis with `STATS COUNT(*) BY category` over the window.
- [ ] Point 4: check whether the Stage I volume alert fired, and when, versus detection.

## Technique card: pivoting from a trace_id
```esql
FROM traces-generic.otel-default
| WHERE trace_id == "<paste id>"
| EVAL ms = duration / 1000000
| KEEP @timestamp, resource.attributes.service.name, name, status.code, attributes.error.category, ms
| SORT @timestamp ASC
```
Read it top to bottom; the deepest span with `status.code = Error` is closest to the cause.
