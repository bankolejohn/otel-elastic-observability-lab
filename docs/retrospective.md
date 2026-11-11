# Retrospective: did we hit the objective?

Written 2026-11-11, on the last day of the Elastic Cloud trial, from the repo and the live cluster rather than from memory.

## The objective (from the first message)

Build a full-stack app locally, instrument it with OpenTelemetry, send traces/metrics/logs through an OpenTelemetry Collector into Elasticsearch on an Elastic Cloud trial, and use it to:
1. understand distributed tracing, spans, and how logs connect to traces;
2. learn how Elasticsearch stores, indexes and searches telemetry;
3. explore anomaly detection and machine learning for monitoring;
4. simulate failures, slow responses and dependency issues, then use telemetry to find the causes.

The stated goal: understand the complete flow from generating telemetry to using it to troubleshoot. A second requirement: do justice to the Elastic Streams article.

## Verdict

| objective | verdict | evidence |
|---|---|---|
| Full-stack app, instrumented with OTel | **Met** | 3 services plus a browser frontend; automatic and hand-written spans, metrics and correlated logs. One order produces a 29-span trace from the browser click down to individual SQL statements (Stage H). |
| Collector forwards all three signals to Elastic Cloud | **Met** | At review time: 72,388 trace, 17,202 log and 278,764 metric documents in Elasticsearch. |
| 1. Tracing, spans, log-trace correlation | **Met** | Shared `trace_id` across services (Stage B); trace pivots used in all three drills. |
| 2. How Elasticsearch stores, indexes, searches | **Mostly met** | Data streams, index/component templates, ingest reroute pipelines, `logsdb`, explicit keyword vs `flattened` mapping, `_field_caps`, histogram temporality. Not covered: lifecycle/retention tuning, sharding and replicas (serverless hides them), storage cost. |
| 3. Anomaly detection and ML | **Met, with caveats** | Two jobs built; the history requirement observed first-hand; one job later flagged real bursts. Caveats below. |
| 4. Simulate failures and investigate | **Met** | Five fault modes plus real container outages (Stage G), then three blind drills with postmortems and a measured alert response. |
| The complete flow, telemetry to troubleshooting | **Met** | Every step exists and was exercised end to end. |

## Correcting what we said about ML

Earlier docs (Stage F, Stage 2, the alert review) said the ML jobs never flagged anything and treated that as the article's lesson. Querying the cluster today shows that was incomplete:

| job | non-empty buckets | highest score |
|---|---|---|
| `service_request_spikes` | 598 of 18,624 | 99.4 |
| `obs_shop_error_spikes` | 17 of 15,870 | 0.0 |

`service_request_spikes` flagged the drill-1 burst (orders-service: 879 spans in a minute vs. a typical ~8, score 99.4), the drill-2 burst (989 vs ~9, score 93.9), and even the 40-order baseline burst sent just before drill 1. So ML anomaly detection **does work once it has history**. The deciding factor was baseline data (598 non-empty buckets vs. 17), not the technique.

Three consequences:
- **The ML alert watches the wrong job.** It points at `obs_shop_error_spikes` (the under-trained one), so it could never have fired. It should point at `service_request_spikes`.
- **What it detected is volume, not failure.** `high_count` flags unusual traffic. The drills were detected because the load generator sent roughly 120 requests a minute against a quiet baseline. That proves the mechanism but is a weaker claim than "ML detects outages".
- **Later bursts scored a little lower** (99.4 for drill 1, 93.9 for drill 2). With two data points that is suggestive, not proof, of the article's lesson that a model trained on spiky traffic starts treating spikes as normal.

The hard-threshold alert still did what the article says it should: it fired about 55 seconds after drill 1, and the latency alert caught the silent `slow` drill that nothing else could.

## How well does it do justice to the article?

| article element | status |
|---|---|
| Parent stream, per-category children, catch-all, reroute pipeline, `logsdb` | **Built and verified**, including a deliberate catch-all test. |
| Classify at ingest | **Deviation, documented**: classified in application code (we own the producer) rather than parsed from message text (ADR-0015). |
| Reroute raw errors into the hierarchy | **Deviation, documented**: done by a Collector transform plus dynamic index routing, so Elastic's managed log template was left alone (ADR-0016). |
| ES|QL for ad hoc investigation | **Used constantly**; see `docs/esql-cheatsheet.md`. |
| ML job and datafeed over the hierarchy, `query_delay` | **Built**; `query_delay` set to 30s against a few seconds of shipping lag. |
| Three alert types | **Built**: volume, pipeline-health (adapted), ML; plus a fourth, the latency alert. |
| Lesson: mapping gotcha | **Hit and fixed for real** (ADR-0017). |
| Lesson: ML alone is not an outage detector | **Observed in a more nuanced form** (section above). |
| Lesson 1: `query_delay` longer than shipping lag | Configured correctly, **not experienced** as a failure. |
| Lesson 3: template silently overwritten | **Not exercised.** |
| Lesson 4: `_reindex` cannot backfill child streams | **Not tested directly**; we deleted and recreated streams instead. |
| Lesson 5: "no data" is not "broken" | Addressed by the pipeline-health alert, which stayed quiet because nothing broke. |

Verdict: the pattern is faithfully built and understood; three of the article's five production lessons were not hit first-hand.

## Honest gaps

1. **The ML alert watches the wrong job** (above). Easy fix.
2. **No alert notifies anyone.** Rules fire and recover, but no email/Slack connector is attached, so nothing would actually page a person.
3. **Metrics were collected but never used to investigate.** Every diagnosis used traces and logs; the ~279k metric documents sat unused.
4. **Not production-shaped.** One instance of each service, Docker Compose, no host/infra metrics, no load balancer. We judged DNS/TLS/real servers not worth the time; multi-instance and host metrics would have added real diagnostic questions.
5. **The dashboard is unfinished.** The 99% and 500 ms reference lines, an error-category panel and a per-span baseline panel are still open.
6. **Three drills is a small sample.** Detection and root-cause times were never recorded, so speed was never measured.
7. **Stage K is only half done.** The request-volume job matured; the error job (errors are rare by design) did not.

## An honest note about learning

The system and the documentation meet the objective. The harder question is how much of the *skill* transferred.

What the evidence shows: across three blind drills the diagnosis went from partly correct (named the cause beside a wrong one) to correct with a trace ID to correct on a silent fault, and the responder reasoned about cause versus symptom unprompted ("this could be the issue that led to other issues"). The earlier traps, reading the tail of a cascade and reporting the root span as the cause, were each corrected once.

What it doesn't show: fluency in writing queries. The responder said plainly that the ES|QL was unfamiliar, and most of the building (Collector config, pipelines, ML jobs, alert rules) was done by the assistant. Reading and diagnosing came across well; authoring from scratch has not been practised. The best way to close that is to redo pieces by hand: the exercises in `docs/esql-cheatsheet.md`, then rebuilding one stage (for example the Collector config in Stage C/D) without help.

## Suggested next steps
1. Point the ML alert at `service_request_spikes` and confirm it fires on a burst.
2. Attach a notification action to the volume and latency rules so an alert reaches a person.
3. Finish the dashboard (reference lines, error-category panel, per-span baseline panel), then re-export it.
4. Run another blind drill, recording detection and root-cause times.
5. Work through the ES|QL exercises, then rebuild one stage unaided on a local Elasticsearch (see start-local in the cheat-sheet).

## Gap closure log (2026-11-11, same day)

| gap | status | evidence |
|---|---|---|
| 1. ML alert watched the wrong job | **Closed and validated** | Rule now watches `service_request_spikes` (severity >= 50). A healthy 150-second burst (`scripts/burst_load.sh`) scored 99.4 and 95.6 for inventory-service (1,516 spans/min vs a typical ~12) and the alert **fired about 2 minutes in** (13:58:05). |
| 3. Metrics never used in an investigation | **Closed** | `metrics.db.client.connections.usage` (state `used`) shows inventory-service pinned at exactly **5, its pool size**, for the four minutes of drill 2 (10:43-10:46) and 0 before, after, and in healthy traffic. Saturation was readable from a metric without opening a trace. New alert "DB connection pool saturated" (`kibana/rules/db-pool-saturation.json`): tested on the drill-2 window (flags inventory-service) and on healthy traffic (no rows); it stayed quiet during the healthy burst. |
| 5. Dashboard unfinished | **Closed (confirmed visually by the user)** | `kibana/dashboards/obs-shop-red-dashboard-v2.ndjson` imported as a new dashboard (the original is untouched). See `docs/stages/stage-j-red-dashboard.md`. |
| 2. Alerts notify nobody | **Closed and validated end to end** | All five rules now email through the preconfigured `Elastic-Cloud-SMTP` connector (once when an alert becomes active). A test email was accepted by the mail server; then 12 real failures fired the volume alert 50 seconds later (14:17:26) and the event log shows the email action executed with outcome `success` four seconds after that. Rule definitions are in `kibana/rules/` with the recipient as a placeholder. |
| 4. Single instance / no infra metrics | **Not done** | Needs a stack change that can only be verified against a live cluster. |
| 6. Drill timings never recorded | **Habit, not code** | Next drill: write down the time at detection and at root cause. |

### New evidence about ML (from the burst test)

The same healthy burst was scored very differently per service:

| service | actual spans/min | typical | score |
|---|---|---|---|
| inventory-service | 1,516 | ~11.8 | **99.4** |
| orders-service | 1,662 | ~0.4 | **1.8** |
| api-gateway | 910 | ~2.4 | **2.2** |

In drill 1 (three hours earlier) orders-service scored 99.4 for a *smaller* burst (879 spans). Now a burst nearly twice as large scores 1.8. The most likely reading is the article's Lesson 2 happening live: after repeated heavy bursts, the model for those services has started treating bursts as normal, while inventory-service's model has not yet. That is an interpretation of two comparisons, not a proven mechanism, but it is the strongest evidence in the project that an ML score alone cannot be relied on, and why the hard-threshold alerts remain the dependable catchers.

### A claim we got wrong, found while writing the reproduction guide

The README said the stack "runs fully locally without Elastic Cloud". That had never been tested. Testing it showed that with empty Elastic credentials the Collector **refuses to start** (`endpoint must not be empty`), so a newcomer following the Quick start would have had a broken stack. Fixed by giving `docker-compose.yml` safe placeholder defaults (verified: empty variables fall back to the placeholders, the Collector runs with dummy values, and the real `.env` values still win). Likewise, running the new `scripts/setup_elastic.sh` against the live cluster exposed two bugs in the exported definitions (server-managed fields that Elasticsearch rejects on write) before anyone else met them, and the create paths for ML jobs, datafeeds and alert rules were tested with throwaway copies.
