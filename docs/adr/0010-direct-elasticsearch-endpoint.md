# ADR-0010: Use the direct Elasticsearch endpoint, not Elastic's OTel-quickstart ingest gateway

Date: 2026-10-29
Status: Accepted

## Context

Elastic Cloud's "Add Observability data -> OpenTelemetry" screen hands out
an endpoint + API key meant to get you ingesting quickly. During Stage D
setup, using that endpoint produced a working-*looking* exporter (the
Collector got real validation responses back, e.g. about dropped
histogram metrics -- not a connection error) but the data never appeared
in the project: `GET _data_stream` against the project's real
Elasticsearch endpoint came back `{"data_streams": []}` even after
multiple orders and repeated waits.

Diagnosis: that quickstart endpoint's root response (`GET /`) returned
`"name": "managed-inputs"` -- not a real cluster node name -- and
`_search`/`_cat/indices` against it both 404'd with a plain-text
(non-Elasticsearch-shaped) response. That's the signature of a narrow,
write-only ingest proxy sitting in front of the real cluster, not the
cluster itself. The real, queryable endpoint was found a completely
different way: Kibana's own **Dev Tools -> Console settings -> "Elasticsearch
host"** field -- guaranteed correct because Dev Tools' own queries were
already working against it (`GET _data_stream` succeeded from inside
Kibana before we had the right endpoint for our own `.env`).

## Decision

`ELASTIC_ENDPOINT` holds the direct Elasticsearch endpoint from Kibana's
Console settings (`Elasticsearch host` field) -- confirmed by its root
response showing `"build_flavor": "serverless"` and a working `_search` --
not the endpoint surfaced by the "Add Observability data" onboarding
screen.

## Alternatives considered

- **Keep using the OTel-quickstart gateway endpoint.** It may well be a
  legitimate Elastic product (a managed intake/forwarding tier), but it
  didn't make data appear in *this* project's cluster during testing, and
  more importantly, it's opaque: we can't query it directly to verify
  anything, which matters for every later stage (Stage 2's ingest
  pipelines and ML jobs both need direct Elasticsearch API access
  regardless). Using it would mean verifying everything secondhand
  through Kibana's UI instead of being able to inspect the data directly.
- **cloudid instead of a raw endpoint URL.** Tried first (simpler-looking
  config); the value pasted into `ELASTIC_CLOUD_ID` from the onboarding
  screen turned out to actually be a URL, not a true Cloud ID string, so
  the exporter config was switched from `cloudid:` to `endpoints:` to
  match what was actually available. Either config field works fine with
  the real endpoint; URL happened to be what was on hand.

## Consequences

- Setup takes one extra step (finding Console settings) instead of
  copy-pasting from the guided onboarding screen, but what's in `.env` is
  now verifiable independently with a plain `curl`, which mattered
  immediately for debugging and will matter again in Stage 2.
- If Elastic's onboarding screen is revisited later (e.g. for a quicker
  path for someone else following this project), treat whatever it hands
  out as suspect until independently verified with the same two checks
  used here: `GET /` should look like a real cluster (not
  `"managed-inputs"`), and `GET <endpoint>/_search` should return a normal
  Elasticsearch response, not a 404.

## Revisit when

If Elastic changes what the onboarding screen provides, or if a future
stage specifically wants to exercise the managed ingest path as its own
lesson (it's a legitimate thing to learn, just not what this project
needed right now).
