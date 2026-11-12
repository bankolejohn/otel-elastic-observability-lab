# Drill 5 — query_timeout under production-like load (k6)

**Date:** 2026-11-12. **Injected:** 09:58:09Z, ~4 minutes. **Actual fault:** `query_timeout` (inventory-service `pg_sleep(8)` per stock query). Run together with `scripts/k6_production_like.js` (12-minute compressed day, flash sale, retries on 5xx).

## Result

**Not scored for root-cause correctness.** The responder gathered good evidence but never committed a single-fault diagnosis or T2 before asking for the reveal (same outcome as drill 4).

## Detection

- T1: 10:58 local (09:58Z), the ML request-volume alert, within seconds of injection. Six alerts in total.
- Dashboard: availability fell from about 100% to near 0% and recovered about 5 minutes later; orders reached over 200 per minute; p95 spiked to about 2.2 s.
- Error categories: `pool_exhausted` (over 1,000) and `query_timeout` (about 150).

## What the signals meant

The injected fault was `query_timeout`, but the loudest category was `pool_exhausted`. Each 8-second query holds a connection (pool size 5), so the pool fills almost immediately and most other requests wait 3 s and fail as `pool_exhausted`. The secondary, quieter category was the real cause. This is the same lesson as drill 2: **the biggest row in the error chart can be a consequence, not the cause.** To separate them, find which category appears first in the window, and look at the span with the longest duration (about 8 s means a stuck query, not a wait for a connection).

## k6 results (whole run)

2,680 requests; orders: 16.9% 5xx (SLO 1%), p95 3.52 s (SLO 1 s). Both thresholds crossed, as expected during an injected fault. 239 retries (client retries amplified load during the fault). Overall checks 89.6%.

## Side finding: telemetry path under load (not the injected fault)

The responder saw frequent `Failed to export traces to otel-collector:4317 ... DEADLINE_EXCEEDED`. This is the apps failing to reach the Collector, so incident traces may be incomplete. **Cause not confirmed.** The responder suspects the Collector `memory_limiter` (`limit_mib: 200`); I could not verify this. My scan of the last 4,000 Collector log lines found no refusal, drop or timeout messages, and `docker stats` calls hung, so no CPU or memory numbers exist. Another candidate is the `debug` exporter with `verbosity: detailed`, which prints every record at 200+ requests per minute. Both are untested hypotheses.

## Action items

1. Test the exporter failure: rerun k6 with `docker stats` sampling, then change `debug` verbosity to `basic` and/or raise `limit_mib`, and see which removes the errors.
2. Add a pipeline-health alert for exporter failures.
3. Do not treat the volume alert as a diagnosis; it fires on any load change, including the load generator.
4. Require a committed diagnosis before the reveal (second drill in a row without one).
5. Record load-generator activity in the incident log, since it distorts rate and ML alerts.
