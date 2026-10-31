# ADR-0019: Browser OTel via CDN ESM, CORS on the Collector, and pinning `@opentelemetry/api` per-package

Date: 2026-11-01
Status: Accepted

## Context

ADR-0006 deferred browser instrumentation specifically because it would
introduce a genuine cross-origin request (browser page on :8000, OTel
Collector on :4318) and, per OpenTelemetry's own documentation, browser/
client instrumentation is "experimental and mostly unspecified." Both
turned out to be exactly right. Getting `services/api-gateway/static/otel-web.js`
working took five real, sequential, live-browser-confirmed bugs, each
with a distinct, specific cause:

1. `@opentelemetry/resources` (resolved to v2.x by esm.sh) removed the
   `Resource` class export in favor of a `resourceFromAttributes()`
   factory function. (`Uncaught SyntaxError: ... doesn't provide an
   export named: 'Resource'`)
2. `WebTracerProvider` removed the `addSpanProcessor()` instance method
   in favor of a `spanProcessors` constructor option. (`TypeError:
   provider.addSpanProcessor is not a function`)
3. The big one: left to resolve each package independently, esm.sh gave
   `sdk-trace-web` its own separate copy of `@opentelemetry/api` (v1.9.1)
   distinct from the one imported directly in `otel-web.js` (v1.10.0).
   OpenTelemetry's API relies on a single shared global registry
   (`setGlobalTracerProvider`/`setGlobalPropagator`/
   `setGlobalContextManager`); two different module instances means two
   different registries, so `provider.register()` silently connected to
   nothing instrumentation code could see. No error was visible by
   default, because OTel's internal diagnostic logger (`diag`) is a
   silent no-op unless a real logger is explicitly installed --
   `diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.WARN)` is what
   surfaced the actual registration errors.
4. Over-correcting #3 by forcing *every* package to the same pinned
   `@opentelemetry/api` version (via esm.sh's `?deps=` parameter) broke
   `exporter-trace-otlp-http`, whose own dependency chain needs a
   `SeverityNumber` export from the separate `@opentelemetry/api-logs`
   package -- the blanket override collided with that resolution.
5. Narrowing the pin to only the packages that actually touch the global
   registry (`sdk-trace-web`, `instrumentation`, `instrumentation-fetch`,
   `instrumentation-document-load`) fixed #4, but revealed a second,
   separate version problem: the specific version pinned first (1.9.1,
   matching what `sdk-trace-web` originally resolved on its own) was too
   old to provide a `logs` named export that the current
   `@opentelemetry/instrumentation` package's code expects. Switching the
   pin to 1.10.0 (what the top-level import had resolved to by default,
   before any pinning) satisfied both sides.

## Decision

- Load the OTel Web SDK via native ES module `import()` straight from
  `esm.sh` (a CDN that resolves npm packages into browser-ready ESM on
  the fly) -- no bundler, consistent with ADR-0006.
- Pin `@opentelemetry/api` to an exact version (`1.10.0`) and force only
  the packages that touch the global tracer/propagator/context registry
  to resolve their internal copy of it to that exact same version, via
  `?deps=@opentelemetry/api@1.10.0` on those specific imports. Leave
  `exporter-trace-otlp-http`, `sdk-trace-base`, `resources`, and `core`
  unpinned -- they don't touch the registry and pinning them caused a
  different, real breakage (see #4 above).
- Enable OTel's diagnostic logger (`DiagConsoleLogger`, level `WARN`) in
  `otel-web.js` permanently, not just while debugging -- its silence is
  exactly what made bug #3 invisible, and it's cheap to leave on.
- Add a `cors` block to the Collector's OTLP HTTP receiver
  (`otel-collector/config.yaml`), allowing `http://localhost:8000`
  explicitly -- CORS is enforced by the browser, not by anything
  docker-compose provides for free.
- `FetchInstrumentation`'s `propagateTraceHeaderCorsUrls` is set to match
  our own backend origin, so the browser's span becomes the parent of
  api-gateway's server span for the same request, joining one trace
  across the browser/backend boundary.

## Alternatives considered

- **Add a build step (npm + bundler) just for the frontend.** Would
  sidestep the whole esm.sh dependency-resolution saga (a bundler dedupes
  shared dependencies correctly by default). Rejected -- contradicts
  ADR-0006's deliberate no-build-step choice, and the debugging journey
  above, while long, is itself a genuine, valuable lesson about exactly
  why OTel's browser story is "experimental" -- worth having gone
  through, not worth architecting around for this project.
- **Give up and skip browser instrumentation.** It was the one piece of
  "full-stack" this project had never actually touched (every other
  stage instruments the backend only). Worth the five-bug slog for that
  reason alone.

## Consequences

- Confirmed end-to-end, for real: placing an order produces a single
  trace with the browser's own `POST` span (no parent -- the true root)
  as the direct parent of api-gateway's server span, which continues
  through orders-service, inventory-service, and individual SQL
  statements -- 29 spans, one trace, starting in the browser. See the
  Stage H doc for the full captured evidence.
- `otel-web.js` is now one of the most heavily-commented files in the
  project, on purpose -- every one of the five fixes has an inline
  comment explaining the real error it fixes, since none of these are
  guessable from reading current documentation alone.

## Revisit when

If esm.sh or any of these packages' resolution behavior changes again
(plausible, given how fast this ecosystem has already moved during this
one project), re-verify via the browser Console with `DiagLogLevel.DEBUG`
before assuming a future change is unrelated.
