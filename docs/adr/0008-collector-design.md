# ADR-0008: Collector image, processors, exporter, and health-check choices

Date: 2026-10-29
Status: Accepted

## Context

Stage C introduces the OpenTelemetry Collector as its own container. Four
small decisions needed making: which Collector distribution/image, which
processors to run, which exporter to use as the Stage C destination, and
how (or whether) to health-check the container.

## Decision

1. **Image: `otel/opentelemetry-collector-contrib`, pinned to `0.153.0`**
   (not the core `otel/opentelemetry-collector` image, and not `:latest`).
2. **Processors: `memory_limiter` then `batch`**, in that order, in every
   pipeline.
3. **Exporter: `debug`** (verbosity `detailed`) as the only exporter for
   now.
4. **No Docker healthcheck** on the `otel-collector` service.

## Alternatives considered

- **Core `otel/opentelemetry-collector` image.** Smaller, and sufficient
  for Stage C (otlp receiver, memory_limiter/batch processors, and debug
  exporter are all in core). Rejected because Stage D needs the
  `elasticsearch` exporter, which only ships in the contrib distribution —
  starting on contrib now means Stage D is a config-only change (add an
  exporter block), not an image swap plus a re-verification of everything
  that already worked.
- **`:latest` tag.** Convenient, but makes the build non-reproducible —
  "it worked yesterday" becomes a real risk since the Collector's config
  schema does change between minor versions. Pinned to a specific tag
  (`0.153.0`, latest stable at the time of writing) instead, same
  reasoning as pinning the app-level dependencies in Stage A.
- **Skipping `memory_limiter`.** Would still work fine at this project's
  tiny scale. Included anyway because it's the universally-recommended
  first processor in any real Collector pipeline (protects the Collector
  from being OOM-killed if export ever backs up), and leaving it out now
  would mean retrofitting it later instead of just explaining it once,
  here, while traffic is low enough that it never actually triggers.
- **`logging` exporter instead of `debug`.** `logging` is the pre-0.86
  name for the same exporter; using the current name avoids a stale
  config that silently breaks on a Collector version bump.
- **A Docker healthcheck calling `wget`/`curl` against the Collector's
  `health_check` extension.** The contrib image is a minimal/distroless-
  style image with no shell or HTTP client binary inside it to run a
  check with, so a `CMD-SHELL` healthcheck would itself fail even if the
  Collector were healthy. Options would be adding the `health_check`
  extension and polling it from *outside* the container, or accepting
  `depends_on: condition: service_started` (container started, not
  verified ready) and relying on the OTLP exporters' own retry/backoff
  behavior for the brief window before the Collector is actually
  listening. Chose the latter: simpler, and consistent with how OTLP
  exporters are specified to behave (retry transient connection failures)
  — on 2026-10-29's run, no export errors appeared in any service's logs
  during the startup window, consistent with this but not a substitute
  for actually testing Collector-down behavior (that's a Stage G chaos
  exercise: kill the Collector mid-run and watch what each service does).

## Consequences

- One version to track and bump deliberately (`0.153.0`), not a moving
  target.
- The Collector will degrade (drop data) rather than crash under memory
  pressure, once traffic is heavy enough for that to matter — not
  observable at this project's scale, but correct to have in place.
- Stage D should only require editing `otel-collector/config.yaml` to add
  an `elasticsearch` exporter and a destination in each pipeline's
  `exporters:` list, plus credentials — not touching the receivers,
  processors, or the app-side configuration at all.

## Revisit when

If Collector version bumps ever break config compatibility, bump the
pinned tag deliberately and note what changed, rather than floating to
`:latest`.
