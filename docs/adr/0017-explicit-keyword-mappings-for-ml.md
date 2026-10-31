# ADR-0017: Explicit keyword mappings for classifier fields

Date: 2026-10-31
Status: Accepted

## Context

The error-streams component template initially mapped the whole
`attributes` object (and `resource.attributes`) as Elasticsearch's
`flattened` field type -- a reasonable-looking choice, since it's
mapping-conflict-safe for arbitrary, varied attribute keys (the same
property that made it attractive for a learning project with lots of
different, evolving attribute shapes). `_search` term queries against
`attributes.error.category` worked fine under this mapping (confirmed in
Stage 2 verification), which hid the problem initially.

It broke when trying to start the ML datafeed:
`[datafeed-obs_shop_error_spikes] cannot retrieve field
[attributes.error.category] because it has no mappings`. Checked
`_field_caps` directly (the article's own recommended check for exactly
this situation) and confirmed: a `flattened` field's sub-paths are
queryable, but `_field_caps` does not expose them as individually
discoverable, aggregatable fields -- which is what a datafeed needs to
resolve a `by_field_name`/`partition_field_name`.

This is, almost verbatim, the article's own "Mapping gotcha" lesson
("if a field is stored in `_source` but not mapped ... it looks present
in Discover but you can't aggregate or filter on it. Always confirm
your classifier fields are keyword via `_field_caps`") -- reproduced
firsthand rather than read about.

## Decision

Changed the component template (`obs-shop-errors-mappings`) to map
`attributes.error.category` and `resource.attributes.service.name` as
explicit, individual `keyword` fields, instead of folding them into a
generic `flattened` catch-all. Everything else about the document shape
is unaffected.

Because component template changes only apply to *new* backing indices,
not retroactively, the (small, disposable, test-only) existing data
streams were deleted and recreated from scratch rather than migrated --
consistent with the article's own Lesson 4 ("you can't backfill into
child streams with `_reindex`" -- the real fix there is also re-ingestion
through the live pipeline, not a retroactive data migration).

## Alternatives considered

- **Keep `flattened`, and have the ML job analyze a different, already-
  explicitly-mapped field instead** (e.g. `resource.attributes.service.name`
  alone, without `attributes.error.category` as the `by_field_name`).
  Rejected -- `error.category` *is* the classification this entire stage
  is about; working around it instead of mapping it properly would be
  avoiding the actual lesson.
- **Map all of `attributes` explicitly, field by field.** Impractical and
  fragile for a field that legitimately varies (every log line's
  attributes differ) -- `flattened` exists specifically for that case.
  The fix here is narrower and more honest: map the *few* fields that are
  genuinely always-present and intentionally queryable/aggregatable as
  explicit keywords, and leave everything else dynamic.

## Consequences

- Confirmed the fix directly: re-ran `_field_caps` after recreating the
  streams, both fields now report `"aggregatable": true`. The ML
  datafeed then started successfully.
- This component template now has two kinds of fields with different
  guarantees: a few explicit, stable, queryable keywords (the
  classification contract), and everything else dynamically mapped
  (flexible, but not guaranteed aggregatable without checking). That
  split is deliberate and should be preserved -- don't fold
  `error.category` back into a generic catch-all for convenience later.

## Revisit when

If another field needs to be used in an ML job, alert rule, or
aggregation, map it explicitly here first and confirm via `_field_caps`
before building anything on top of it -- don't assume a field that's
visible in a `_search` result is necessarily aggregatable.
