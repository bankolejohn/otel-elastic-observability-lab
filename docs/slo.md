# Service Level Objectives (SLOs) for the obs-shop order flow

This is the contract that defines what "the system is healthy" *means*, in
measured terms. Everything else in the SRE practice plan (the dashboard, the
alerts, the incident drills) is built to serve these. Point 1 of
`docs/sre-practice-plan.md`.

The user journey we care about is **placing an order** -- the single
most important thing this system does. SLOs are defined on that journey as
experienced at the front door (`api-gateway`), because that's closest to what
a real user actually feels. (An SRE principle: measure SLIs as close to the
user as you can.)

## The SLIs (Service Level Indicators -- what we measure)

### SLI 1 — Order availability
> Of all order attempts, what fraction succeeded (did not fail with a
> server error)?

- **Good events**: `POST /api/orders` spans on `api-gateway` with
  `http.status_code` < 500
- **Total (valid) events**: all `POST /api/orders` spans on `api-gateway`
- Deliberately counts only 5xx as "bad". A 409 (insufficient stock) or 404
  (no such product) is the system *correctly* rejecting a bad request --
  that's a success from the system's point of view, not an outage. Only a
  5xx means *we* failed. (This distinction is itself a core SRE judgment
  call: an SLI measures *our* reliability, not the user's mistakes.)

ES|QL:
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders"
| EVAL is_bad = CASE(attributes.http.status_code >= 500, 1, 0)
| STATS total = COUNT(*), bad = SUM(is_bad)
| EVAL availability_pct = ROUND(100.0 * (total - bad) / total, 3)
```

### SLI 2 — Order latency
> Of all successful order attempts, what fraction were served fast enough?

- **Good events**: successful (`http.status_code` == 200) `POST /api/orders`
  spans with `duration` under the latency threshold (see SLO below)
- **Total (valid) events**: all successful `POST /api/orders` spans
- Measured on successes only, on purpose: a failed request's latency isn't a
  meaningful "was it fast" signal -- it's a different failure, already counted
  by SLI 1. (Don't double-count one bad event against two SLOs.)

ES|QL (latency distribution):
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway"
    AND name == "POST /api/orders" AND attributes.http.status_code == 200
| EVAL ms = duration / 1000000
| STATS p50 = PERCENTILE(ms, 50), p95 = PERCENTILE(ms, 95), p99 = PERCENTILE(ms, 99)
```

## The SLOs (the targets -- set from real measured baselines)

Measured baselines on 2026-11-01 (the honest, data-driven part -- targets
below are *not* made up, they're set a realistic notch beyond observed normal):

| metric | observed (clean traffic) | observed (incl. chaos) |
|---|---|---|
| availability | 100% (0 of 292 were 5xx over 2h) | same |
| latency p50 | ~106 ms | ~136 ms |
| latency p95 | ~3100 ms (inflated by `slow` chaos) | ~5700 ms |

The p95 is badly inflated by the `slow`/`query_timeout` chaos modes being
mixed into the same history -- a real lesson: **an SLO baseline measured over
a window full of your own fault-injection tests is not a real baseline.** The
clean-traffic p50 (~106ms) is the honest "normal." Order placement does a
cache lookup + a downstream reserve + a DB write, so a few hundred ms is a
reasonable normal ceiling.

### SLO 1 — Availability
> **99% of order attempts succeed (non-5xx) over a rolling 1-hour window.**

99% (not 99.9%) on purpose: this is a learning system that gets *deliberately*
broken for drills, so a very tight target would be "breaching" constantly by
design. In a real company this journey would likely target 99.9%.

### SLO 2 — Latency
> **95% of successful orders complete in under 500 ms, over a rolling 1-hour
> window.**

500ms is ~5x the clean p50 -- generous enough that normal variation doesn't
breach it, tight enough that the `slow` chaos mode (adds 2s) *will* breach it,
which is exactly what makes it useful for drills.

## Error budget

An SLO of 99% availability over 1h means a **1% error budget**: up to 1% of
orders *may* fail without the objective being breached. This reframes
reliability from "never fail" (impossible) to "fail less than the budget" --
the core idea that makes SLOs actionable instead of aspirational.

At the traffic rate of the steady generator (~1 order / 20s ≈ 180/hour), a 1%
budget is roughly **1-2 failed orders per hour** before SLO 1 is at risk.
Worth remembering during drills: a single injected failure is within budget;
a sustained outage burns through it fast.

## How these drive everything else
- **Dashboard (point 2)**: the RED dashboard's "Errors" and "Duration" panels
  are literally these two SLIs, plotted against these two targets.
- **Alerts (point 4)**: the ideal alert fires when the *error budget* is
  burning too fast to make the 1h window -- not on an arbitrary raw count.
  (The existing Stage I volume alert is a cruder stand-in for this; tuning it
  toward budget-burn is part of point 4.)
- **Drills (point 3)**: "did the SLO correctly reflect that I just broke
  something, and how long until I noticed?" is the scorecard for each drill.

## Status / revisit
- Targets set from a baseline polluted by chaos traffic -- once the steady
  generator has run clean for a while (Stage K), re-measure and tighten if the
  real clean p95 is well under 500ms.
