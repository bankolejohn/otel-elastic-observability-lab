# Alert review (SRE practice plan, point 4) — 2026-11-11

Question: did the Stage I alert rules catch the two drills, how fast, and what are their blind spots? Source: rule status from Kibana's Alerting API and alert history from the `.alerts-*` index.

## Every time an alert has ever fired

| rule | started (UTC) | recovered (UTC) | cause |
|---|---|---|---|
| volume spike | 2026-11-01 15:00:09 | 15:01:09 | Stage I test burst (7 errors) |
| volume spike | 2026-11-03 10:53:09 | 10:54:09 | SLO validation burst (10 failures) |
| volume spike | 2026-11-11 10:15:27 | 10:20:27 | **drill 1** (injected 10:14:32) |
| volume spike | 2026-11-11 10:42:27 | 10:48:27 | see caveat below (drill 2 injected 10:42:51) |
| ML anomaly | never | | |
| pipeline health | never | | |

**Caveat on drill 2:** the alert started 24 seconds *before* the drill was injected. It was tripped by my 60-request verification burst for the chaos-tooling fix (10:41:53 onward). So drill 2's detection time cannot be measured, and any replay over its window includes about 61 test failures that were not part of the drill.

## Findings

1. **Detection latency (drill 1): about 55 seconds** (injected 10:14:32, alert started 10:15:27). Bounded by the 1-minute rule schedule. Acceptable.
2. **It stayed active for exactly 5 minutes** (the length of its window) and recovered about 2 minutes after the fault actually ended (~10:18:30).
3. **The count threshold is not tied to the SLO.** The rule fires on more than 5 error *documents* in 5 minutes. Each failed order is logged by two services, so that is roughly 3 failed orders. At the steady generator's rate (about 13 orders per 5 minutes) that is roughly a 20% failure rate, versus an SLO breached at 1%.
4. **But a stricter rule is not obviously better at this scale.** With about 13 orders in a window, one failure already drops availability to ~92%, so a pure "availability below 99%" rule would page on a single failed order. Proper SLO alerting (burn rate over longer windows) needs more traffic than this lab produces. The count rule is not broken here; its weakness is that it does not scale with traffic.
5. **The real blind spot is latency.** The rule counts error documents. The `slow` fault produces none, and SLO 2 (95% of orders under 500 ms) has no alert at all. A slow-but-succeeding incident would be invisible to every rule.
6. **The ML alert never fired**, including during two drills sending about 120 failing requests per minute. This matches Stage F and Stage 2 and the reference article's lesson: the hard threshold is the dependable catcher, ML is a supplement.

## Replay of an SLO-style availability query against the real drills (read-only)

`availability = 100 * (total - 5xx) / total` for `POST /api/orders` on api-gateway, over the 5-minute window ending ~1 minute after injection:

| window | total | bad | availability |
|---|---|---|---|
| drill 1 (10:10:32-10:15:32) | 171 | 122 | 28.7% |
| drill 2 (10:38:51-10:43:51; includes ~61 test failures) | 194 | 157 | 19.1% |
| healthy, last 5 min | 13 | 0 | 100.0% |

The SLI separates healthy from broken cleanly, so it is a sound basis for an alert if traffic grows.

## Decision
- Keep the existing volume rule unchanged.
- Add a **latency alert** (p95 of successful orders above 500 ms, with a minimum request count), because that is the proven gap.
- Validate it with a `slow` drill: the volume rule should stay silent and the latency rule should fire.

## Status
- [x] Reviewed when and whether each rule fired
- [x] Identified the blind spot (no latency alert) and the scale limits of the count rule
- [ ] Latency alert created
- [ ] Validated by a `slow` drill
