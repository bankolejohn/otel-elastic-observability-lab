# ADR-0016: Collector-side dynamic routing into a dedicated hierarchy

Date: 2026-10-31
Status: Accepted

## Context

The reference article's Streams pattern starts with raw logs landing in
one index, with a `default_pipeline` that reroutes error documents into
the Streams hierarchy. We already have a working, Elastic-managed log
destination (`logs-generic.otel-default`, set up in Stage D). Two ways to
get our classified error logs into a new, dedicated hierarchy
(`logs.obs-shop.errors` and children): modify the *existing* stream's
template to add a reroute pipeline (closest to the article's literal
approach), or divert matching documents at the Collector, before they
ever reach that stream.

## Decision

Added a `transform` processor to the Collector's logs pipeline
(`otel-collector/config.yaml`) that tags any log record carrying our
application-set `error.category` attribute with
`elasticsearch.index: "logs.obs-shop.errors"`. The `elasticsearch`
exporter's "dynamic index attribute" routing mode reads that tag and
sends *only* those documents to our new hierarchy; everything else is
untouched and keeps landing in `logs-generic.otel-default` exactly as
before.

## Alternatives considered

- **Create a higher-priority index template matching
  `logs-generic.otel-default`'s own pattern, adding a `default_pipeline`
  there.** This is what the article itself does (and is, structurally,
  more faithful to it) -- but index template resolution picks exactly
  *one* template per matching index, by priority; it doesn't merge
  multiple templates together. A new, higher-priority template would
  need to exactly replicate every component template Elastic's own
  managed OTel integration composes, just to add one pipeline reference,
  or risk silently losing mappings/settings on the next rollover for an
  already-working, already-verified pipeline (Stages D-G). Given how
  much pain Stage D already cost from guessing at Elastic-managed
  infrastructure, modifying it further without being certain of its full
  composition was judged not worth the risk, for a gain (literal fidelity
  to the article's mechanism) that a Collector-side equivalent achieves
  just as well in practice.
- **Have each service export error logs via a second OTLP exporter
  pointed at a different destination.** Would require every service to
  know about the Streams hierarchy's existence, which defeats the
  Collector's whole purpose (Stage C) of keeping that knowledge in one
  place.

## Consequences

- The "reroute error events into the hierarchy" step from the article
  happens in the Collector, not in an Elasticsearch ingest pipeline --
  a deliberate, documented departure from the article's literal
  mechanism, for a safety reason specific to this project's history, not
  a claim that it's a universally better choice.
- The *second* hop (parent -> child streams, by category) is still a
  real Elasticsearch ingest pipeline with a `reroute` processor,
  unchanged from the article's actual approach -- see ADR for the
  ingest pipeline itself, documented in the Stage 2 doc.
- `logs-generic.otel-default` is completely unaffected: confirmed
  directly, error-classified documents sent after this change do not
  also appear there (they only ever land in the new hierarchy).

## Revisit when

If a future need specifically requires the literal article mechanism
(e.g. demonstrating the "index template priority" lesson for real), that
would be a deliberate, separate exercise -- not a reason to change this
decision for the main pipeline.
