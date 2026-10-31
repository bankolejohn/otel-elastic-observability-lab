# ADR-0012: Custom ML anomaly job via direct API, not Kibana's built-in APM anomaly detection toggle

Date: 2026-10-30
Status: Accepted

## Context

The original Stage F plan (from the project roadmap agreed at the start)
was "turn on Kibana's built-in APM anomaly detection" -- a per-service
toggle that lives inside the Applications/APM UI's Service Inventory.
Stage E established that this UI doesn't recognize our services at all,
because it depends on APM-specific derived metrics that only Elastic's
own APM connector produces, and we deliberately don't run that component
(ADR-0008). That toggle isn't reachable with this architecture.

## Decision

Built a custom ML anomaly detection job directly against Elasticsearch's
`_ml` API (`service_request_spikes`): a `high_count` detector partitioned
by `resource.attributes.service.name`, `bucket_span: 1m`, fed by a
datafeed reading `traces-generic.otel-default` with `query_delay: 30s`.
Created and started via raw API calls (`PUT _ml/anomaly_detectors/...`,
`PUT _ml/datafeeds/...`, `_open`, `_start`), the same mechanism the
reference Medium article uses, not a UI wizard.

## Alternatives considered

- **Chase down getting the Applications UI toggle working** (e.g. by
  adding Elastic's APM connector to the Collector pipeline). Rejected:
  contradicts ADR-0008's deliberate choice, and would mean learning a
  second, Elastic-specific ingestion path on top of the plain-OTel one
  this project is built around, for a feature that's ultimately a UI
  convenience over the same underlying ML API we can call directly.
- **Skip anomaly detection entirely for now, wait for Stage 2.** Rejected
  -- doing a small, real version of it now, on our own data, is a much
  better rehearsal for Stage 2's more elaborate version (per-category
  child streams, multiple detectors) than reading about it cold when we
  get there.

## Consequences

- This is actually a *better* match for the project's end goal (the
  Medium article) than the original plan was: the article's entire
  anomaly-detection section is built on this same raw `_ml` API, not a
  UI toggle, so this stage is now direct practice for Stage 2 rather
  than a detour from it.
- No Kibana UI wizard walkthrough for creating an ML job -- worth doing
  once in the UI later (Kibana -> Machine Learning -> Anomaly Detection)
  just to see the create-job wizard, but the job itself already exists
  and is running regardless of whether that UI is ever opened.

## Revisit when

If a future stage specifically wants to exercise Elastic's APM-native
tooling (its own connector, Service Map, built-in per-service anomaly
toggle) as a deliberate comparison point against the plain-OTel approach
used throughout this project.
