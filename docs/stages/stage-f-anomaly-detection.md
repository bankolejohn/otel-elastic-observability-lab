# Stage F — Anomaly detection on our telemetry

Status: **Complete**
Related ADRs: [0012](../adr/0012-custom-ml-job-not-apm-toggle.md)

## What

A real Elasticsearch ML anomaly detection job, `service_request_spikes`,
running continuously against our own trace data — created via the raw
`_ml` API (the same mechanism the reference Medium article uses), not a
UI wizard. It did not flag our test spike as anomalous, and that result
is itself the lesson this stage was supposed to teach.

## Why

The original plan was to toggle Kibana's built-in per-service APM anomaly
detection. Stage E established that path isn't reachable with this
project's architecture (no APM connector, so Applications/Service
Inventory doesn't recognize our services — see ADR-0012). Building the ML
job directly via the API turned out to be a better fit anyway: it's
literally the mechanism Stage 2 (the reference article) uses, just at
smaller scale, so this stage is now direct rehearsal rather than a
detour.

## How it works

```
PUT _ml/anomaly_detectors/service_request_spikes
{
  "analysis_config": {
    "bucket_span": "1m",
    "detectors": [{
      "function": "high_count",
      "partition_field_name": "resource.attributes.service.name"
    }],
    "influencers": ["resource.attributes.service.name"]
  },
  "data_description": { "time_field": "@timestamp" }
}

PUT _ml/datafeeds/datafeed-service_request_spikes
{
  "job_id": "service_request_spikes",
  "indices": ["traces-generic.otel-default"],
  "query": { "match_all": {} },
  "query_delay": "30s",
  "frequency": "30s"
}
```

Then `_open` the job and `_start` the datafeed (with a `start` timestamp
from before our earliest data, so it backfills over everything we've
generated so far before continuing in real time).

## How to verify

```bash
set -a; source .env; set +a

# Job is open and processing
curl -s -H "Authorization: ApiKey ${ELASTIC_API_KEY}" \
  "${ELASTIC_ENDPOINT}/_ml/anomaly_detectors/service_request_spikes/_stats"

# Bucket-level scores, highest first
curl -s -H "Authorization: ApiKey ${ELASTIC_API_KEY}" -H "Content-Type: application/json" \
  "${ELASTIC_ENDPOINT}/.ml-anomalies-service_request_spikes/_search?pretty" \
  -d '{"query":{"term":{"result_type":"bucket"}},"sort":[{"anomaly_score":"desc"}],"size":5}'
```

**Actually run on 2026-10-30:** job created and opened cleanly, datafeed
started from `2026-10-29T00:00:00Z` and caught up on all historical data
within seconds (`state: "opened"`, no errors). Fired a deliberate burst
of 40 concurrent order requests to create a real spike. After waiting for
the bucket to close and the `query_delay` to pass, checked results:

- Total buckets: **1119**. Non-empty buckets: **5**. (Everything else is
  zero — our test traffic across this whole project has been sparse and
  clustered in short bursts during verification, not steady background
  load.)
- The five non-empty buckets' `event_count`: **901, 95, 72, 29, 9**. The
  901 is our deliberate burst.
- `anomaly_score` for every single bucket, including the 901-event one:
  **0.0**.

## The actual lesson

This is the reference article's "Lesson 2" (anomaly detection trained on
a bursty platform learns bursts as normal) happening for real, compounded
by a second, equally real problem: with only 5 non-empty observations in
its entire history, the model has nowhere near enough data to build a
confident sense of "normal" in the first place. 901 doesn't look
impossible when the only other things you've ever seen range from 9 to
95 — the sample is too small to rule much of anything out.

Two practical takeaways that transfer directly to Stage 2, where the
stakes are real production log volume instead of a handful of test
requests:

1. **ML anomaly detection needs a real baseline period of consistent
   data before it's trustworthy** — not just "enough buckets to not
   error," but enough *non-empty, representative* buckets to establish
   genuine variance. A model queried too early will look like it's
   working (no errors, clean API responses) while being statistically
   meaningless.
2. **This is exactly why the article insists on a hard-threshold volume
   alert as the real outage detector, with ML as a supplement for subtler
   shifts** — not the other way around. We just reproduced, firsthand,
   why relying on ML alone would have missed a 10x spike.

## What's next

Stage G: chaos. Fault injection (slow responses, DB timeouts, dependency
failures) and using everything built so far — traces, correlated logs,
this ML job, and eventually a hard-threshold check — to diagnose what
broke and why.
