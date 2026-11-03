# Incident drill — orders failing intermittently under load (WORKED EXAMPLE)

**Date:** 2026-11-03 (illustrative)
**Responder:** example
**Drill runner:** example (injected a fault without telling the responder which)
**Status:** resolved

> This is a filled-in example to show the shape of a good postmortem before you
> run your own. The diagnosis path and queries are real against this system;
> treat it as the reference standard, not as a real past incident.

> Blameless. The subject is the system and its signals.

## Timeline

| time | what happened / what I did |
|---|---|
| T+0:00 | "Paged": the Errors panel on the RED dashboard dropped from 100% toward ~60% availability; Rate panel showed a simultaneous bump in orders/min. |
| T+0:30 | Confirmed it's real, not a blip -- availability stayed below the 99% SLO line for 2+ consecutive minutes. SLO 1 is breaching. |
| T+1:10 | Rate was UP, not down -- so we're still serving requests, just failing some. Rules out a total outage / upstream-down. App-level fault. |
| T+1:40 | Error-category panel: `pool_exhausted` spiking, all attributed to `inventory-service`. Nothing in the other categories. |
| T+2:30 | Pulled one failing trace (searched traces for status Error in the window). The `reserve_stock` span on inventory-service carried `error.category: pool_exhausted`, `status.message` referencing QueuePool. |
| T+3:10 | Correlated log on that trace_id: `QueuePool limit of size 5 overflow 0 reached, connection timed out, timeout 3.00`. Confident root cause: inventory-service DB connection pool exhausted under concurrent load. |
| T+3:20 | (reveal) actual injected fault: `/chaos` mode `pool_exhausted` + a 20-concurrent-request burst. Match. |

## Scorecard
- **TTD (time to detect):** 0:30
- **TTR-diagnosis (time to confident root cause):** 3:10
- **Correct?:** yes -- stated "inventory-service pool exhaustion under load", actual was exactly that.

## What actually happened (the real fault)
`pool_exhausted` chaos mode on inventory-service (holds each DB connection
open ~4s), combined with a 20-concurrent-request order burst against a pool of
`size=5, max_overflow=0`. The 6th+ concurrent reservation couldn't get a
connection within the 3s `pool_timeout` and failed.

## How it showed up in telemetry
- **RED dashboard:** Errors dropped below the 99% line; Rate *rose* (the tell
  that it's not an outage); Duration p95 on the surviving successes also rose
  (connections were scarce, so even winners waited).
- **Which service:** the error-category panel attributed every `pool_exhausted`
  to inventory-service -- no ambiguity, straight to the right service.
- **The trace:** the `reserve_stock` span (our own manual span from Stage B)
  carried the error, with the category as a span attribute.
- **The log:** the correlated log line had the literal SQLAlchemy QueuePool
  message with the timeout value -- unambiguous root cause.
- **SLO impact:** availability dipped to ~60% over the burst minute,
  well below the 99% SLO; a chunk of the 1h error budget burned in one minute.

## What worked
- The error-category Streams hierarchy (Stage 2) turned "errors are up" into
  "pool_exhausted on inventory-service" in one glance -- that's what collapsed
  TTR from "hunt through services" to "go straight there."
- Rate going UP while Errors dropped instantly ruled out the whole class of
  "something is down" causes -- a fast, high-value early branch.
- The manual `reserve_stock` span meant the failure had a named, obvious home
  in the trace rather than being buried in a generic DB client span.

## What was slow or misleading
- ~3 minutes to confident root cause is honest but slow. Most of it was
  manually pulling a trace and then its correlated log in two separate steps.
- The generic 500 the *caller* received (api-gateway) carried none of the
  category detail -- if the dashboard hadn't had the category panel, diagnosis
  would have started from a useless "api-gateway is returning 500s" and taken
  much longer. (This is the Stage G "generic 500 masks everything" lesson,
  felt again.)

## Action items
- [ ] Add the error-category breakdown as a permanent dashboard panel (it was
      the MVP of this diagnosis) -- practice-plan point 2.
- [ ] Check whether the Stage I volume alert actually fired during this, and
      at what time vs TTD 0:30 -- if it lagged, tune it -- point 4.
- [ ] Consider a dashboard drill-down link from the category panel straight to
      the matching child stream's logs, to collapse the two-step trace->log
      hunt.
