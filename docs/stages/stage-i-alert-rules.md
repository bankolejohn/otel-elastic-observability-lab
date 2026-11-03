# Stage I — Live alert rules via Kibana's Alerting API

Status: **Complete**

Second post-completion extension, following Stage H (browser instrumentation).

## What

The three alert rules the Stage 2 doc documented as reference
configuration (but didn't create, for lack of the Kibana endpoint) are
now real, live rules in Kibana, created via its Alerting API.

## Why

Stage 2 deferred this specifically to avoid repeating the multi-turn
endpoint-discovery pain from Stage D. This time, finding the Kibana
endpoint was trivial: it's whatever's in the browser's own address bar
while Kibana is open, since the user already had it open.

## How it works

Found the real Kibana endpoint (the `https://<deployment>.kb.<region>.<provider>.elastic.cloud`
host, kept in `.env` as `KIBANA_ENDPOINT`, not committed)
this way, confirmed it works with the same Elasticsearch API key
(`GET /api/status` → 200), then checked `GET /api/alerting/rule_types`
for the real, authoritative parameter requirements before creating
anything blind -- consistent with how every other Elastic-Cloud-facing
piece of this project has been built.

**Rule 1 — volume/outage alert** (`.es-query`): fires if more than 5
documents land in `logs.obs-shop.errors*` within a rolling 5-minute
window, checked every minute. The dependable, hard-threshold catcher —
deliberately simple, no ML involved.

**Rule 2 — pipeline health** (`.es-query`): fires if any document in
`logs-generic.otel-default` has `attributes.error.category` set within
the last 10 minutes. This project's equivalent of the reference
article's "errors piling up in the raw index, unforwarded" check,
adapted to this project's actual routing mechanism (a Collector-side
`transform` processor, not an Elasticsearch ingest pipeline at the first
hop — see ADR-0016). A false trigger here means the Collector's routing
broke, not that errors happened (errors that are correctly classified
never reach this index at all).

**Rule 3 — ML anomaly alert** (`xpack.ml.anomaly_detection_alert`): fires
on `obs_shop_error_spikes`'s own results, `severity >= 25`. Required
discovering the real params shape by trial and error against Kibana's
own validation error (`severity` needed to be a plain number, not an
object, as a first guess assumed).

No notification actions attached to any of the three (no email/Slack
connector configured) — each still evaluates on schedule and tracks its
own fire/recover status, visible in Kibana's Alerting UI and via the API,
which is what mattered for this exercise.

## How to verify

```bash
# Create (see the three request bodies in this project's history / Stage 2 doc
# for the exact params); then:
curl -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  "$KIBANA_ENDPOINT/api/alerting/rule/<rule_id>" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['execution_status'])"
```

**Actually run on 2026-11-01:** generated 7 real `connection_failed`
errors (deliberately above rule 1's threshold of 5), waited for the
rule's 1-minute schedule to run, then checked all three:

| rule | status | meaning |
|---|---|---|
| obs-shop error volume spike | `active` | **fired** — correctly detected the deliberate spike |
| obs-shop error-routing pipeline health | `ok` | correctly found nothing — routing is healthy |
| obs-shop ML anomaly alert | `ok` | correctly found nothing — consistent with Stage F/2's under-trained-model finding |

## What's next

A real Kibana dashboard (Stage J), now that there's genuine browser +
backend + chaos data worth visualizing, and continuing to let the ML
jobs mature (Stage K, ongoing).
