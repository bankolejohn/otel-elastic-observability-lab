# Stage J — The RED dashboard (SRE practice plan, point 2)

Status: **Queries built & verified; panels to be assembled in Kibana UI**

The "RED method" (Rate, Errors, Duration) is a standard way to summarize the
health of a request-serving service on one screen. This dashboard is built to
pass the SRE test: *paged at 3am, can it tell you within 30 seconds whether
things are broken and roughly where?*

All three panel queries below were tested against real data on 2026-11-03
before being written down -- and all three correctly show the fingerprint of
a 10-failure test burst at 10:52 (Rate spikes to 13, Errors drops to 23%
availability, Duration's successful-order latency rises that same minute).
The three panels tell one incident's story from three angles -- which is the
whole point.

## Why ES|QL panels (and the one manual step that remains)

Each panel is a Lens visualization in **ES|QL mode**. The queries are
verified; the only thing left is assembling them in Kibana's UI, because
Lens's hand-authored panel JSON is an internal, unstable format not safe to
POST blind (the same reason the Stage H browser SDK fought back -- "experimental
and mostly unspecified" territory). Building them in the UI means Kibana
validates and renders each one as you go.

## How to build it

Kibana -> Dashboards -> Create dashboard -> Create visualization -> switch the
editor to **ES|QL**. Paste each query, pick the suggested chart type (noted
per panel), save to the dashboard. Set the dashboard's time range to
"Last 1 hour" and auto-refresh to ~30s.

### Panel 1 — RATE (throughput): "are we serving requests?"
Bar or area chart, X = `minute`, Y = `orders`.
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders"
| EVAL minute = DATE_TRUNC(1 minute, @timestamp)
| STATS orders = COUNT(*) BY minute
| SORT minute ASC
```
*What it tells you:* a sudden drop to zero = we've stopped taking orders at
all (hard outage / upstream down). A spike = unusual load (or, in a drill, a
burst of retries).

### Panel 2 — ERRORS (availability vs SLO): "are requests succeeding?"
Line chart, X = `minute`, Y = `availability_pct`. The key move: this is
plotted against SLO 1's target of 99% -- add a static reference line at 99 in
the Lens panel options so the breach is visible at a glance.
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway" AND name == "POST /api/orders"
| EVAL minute = DATE_TRUNC(1 minute, @timestamp),
       is_bad = CASE(attributes.http.status_code >= 500, 1, 0)
| STATS total = COUNT(*), bad = SUM(is_bad) BY minute
| EVAL availability_pct = ROUND(100.0 * (total - bad) / total, 2)
| SORT minute ASC
```
*What it tells you:* the line dipping below the 99% reference line = SLO 1 is
breaching *right now*. This is the single most important panel on the board --
it's the SLO, live.

### Panel 3 — DURATION (latency percentiles): "are requests fast?"
Line chart, X = `minute`, two series: `p50` and `p95`. Add a static reference
line at 500 (SLO 2's latency threshold, in ms).
```esql
FROM traces-generic.otel-default
| WHERE resource.attributes.service.name == "api-gateway"
    AND name == "POST /api/orders" AND attributes.http.status_code == 200
| EVAL minute = DATE_TRUNC(1 minute, @timestamp), ms = duration / 1000000
| STATS p50 = PERCENTILE(ms, 50), p95 = PERCENTILE(ms, 95) BY minute
| SORT minute ASC
```
*What it tells you:* p95 crossing the 500ms line = SLO 2 breaching. p50 and
p95 diverging sharply = *some* requests are slow while most are fine (a tail
problem -- e.g. one slow dependency, or pool contention), which is a very
different diagnosis than *both* rising together (everything is slow -- e.g.
the DB is struggling).

## Optional 4th panel — error breakdown by category
Not part of classic RED, but cheap and very useful during a drill: *which*
kind of error is spiking. Bar chart, X = `category`, Y = `count`.
```esql
FROM logs.obs-shop.errors*
| STATS count = COUNT(*) BY category = attributes.error.category
| SORT count DESC
```
*What it tells you:* turns "errors are up" into "pool_exhausted errors are up
on inventory-service" -- the jump from *symptom* to *cause*, straight off the
dashboard. This is the payoff of the whole Stage 2 Streams hierarchy.

## How to read it as a whole (the 3am test)
1. **Rate** flat/normal but **Errors** dropping -> we're serving requests but
   failing them -> app-level fault (look at panel 4 for which category).
2. **Rate** cratered -> we've stopped serving at all -> something upstream /
   total outage.
3. **Errors** fine but **Duration** p95 climbing -> not failing yet, but
   degrading -> the early-warning case, the one you want to catch *before* it
   becomes errors.

## The saved dashboard
The user assembled the three panels in Kibana and saved them as **obs-shop RED dashboard**. It is exported to `kibana/dashboards/obs-shop-red-dashboard.ndjson` (3 panels with their ES|QL queries embedded, plus the `logs-*` data view; no credentials or hostnames) so it outlives the Elastic Cloud trial.

To restore it in another Kibana: Stack Management -> Saved Objects -> Import, choose the file. Or:
```bash
curl -X POST "$KIBANA_ENDPOINT/api/saved_objects/_import?overwrite=true" \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "kbn-xsrf: true" \
  --form file=@kibana/dashboards/obs-shop-red-dashboard.ndjson
```
The panels query `traces-generic.otel-default`, so they only show data once the stack has been shipping telemetry to that cluster again.

## Lessons from using it in drills
- The dashboard made all three incidents visible (drills 1-3), but the Errors panel plots `total`, `bad` and `availability_pct` on one axis, which hides the 0-100 availability line. Plot `availability_pct` alone with a 99 reference line.
- It still lacks a "typical latency per span" baseline panel and an error-category panel; both would have shortened the drills. See `docs/incidents/`.

## Status
- [x] All three RED queries built and verified against real data
- [x] Confirmed they reflect a real injected incident (the 10:52 burst)
- [x] Panels assembled in Kibana and saved; exported to the repo
- [ ] Reference lines added (99% on Errors, 500ms on Duration)
- [ ] Error-category and per-span baseline panels added

## v2 (2026-11-11): fixing what the drills exposed

Inspecting the exported v1 showed two problems: panels 0 and 1 held the **same** availability query (so there was no separate Rate panel), and the Duration panel was a *stacked* bar chart, which makes p95 look like p50 + p95. v2 (`kibana/dashboards/obs-shop-red-dashboard-v2.ndjson`, imported as "obs-shop RED dashboard v2", original untouched) has five panels:

| panel | chart | notes |
|---|---|---|
| RATE: orders per minute | bar | distinct from Errors |
| ERRORS: availability % vs 99% SLO | line | the SLO is a constant `slo_target = 99` column plotted as a second line |
| DURATION: p50 / p95 vs 500 ms SLO | line (not stacked) | `slo_ms = 500` constant line |
| ERROR CATEGORIES | bar | cause at a glance (the drill-2 MVP) |
| BASELINE: typical ms per span | horizontal bar | answers "how do I know what's slow?"; excludes browser spans |

The SLO "reference lines" are constant columns inside the ES|QL rather than Lens reference-line layers, because Lens's ES|QL mode does not reliably support reference-line layers. Panels were produced by cloning a panel Kibana itself exported and changing its query/columns, not hand-writing Lens state. All five queries were run against live data first. Visual rendering is confirmed by the user in the Kibana UI.
