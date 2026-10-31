// Browser-side OpenTelemetry instrumentation -- no build step, loaded as a
// native ES module straight from a CDN (esm.sh resolves npm packages into
// browser-ready ESM on the fly). Consistent with ADR-0006's choice to keep
// the frontend bundler-free.
//
// NOTE: OpenTelemetry's own docs describe browser/client instrumentation as
// "experimental and mostly unspecified" -- this file is the product of
// three real, sequential bugs found live in a browser, not assumed from
// documentation:
//   1. @opentelemetry/resources v2.x removed the `Resource` class export
//      in favor of resourceFromAttributes().
//   2. WebTracerProvider removed the addSpanProcessor() instance method in
//      favor of a `spanProcessors` constructor option.
//   3. The big one: esm.sh, left to resolve each package independently,
//      gave sdk-trace-web its OWN separate copy of @opentelemetry/api
//      (v1.9.1) distinct from the one this file imports directly (it
//      resolved to v1.10.0). OpenTelemetry's API relies on a SINGLE shared
//      global registry (setGlobalTracerProvider/setGlobalPropagator/
//      setGlobalContextManager) -- two different module instances means
//      two different registries, so provider.register() silently didn't
//      connect to anything instrumentation code could see. No error is
//      thrown by default because OTel's internal diagnostic logger is a
//      silent no-op unless you explicitly enable one (see below) -- that
//      silence is exactly what made this bug look like "nothing is wrong,
//      it just does nothing."
//
// The fix for #3: pin @opentelemetry/api to one exact version ourselves,
// and force every other package to resolve its OWN internal dependency on
// @opentelemetry/api to that *same* URL, via esm.sh's `?deps=` parameter.
// 1.9.1 (tried first, matching what sdk-trace-web's own internal
// resolution originally picked) turned out to predate the `logs` named
// export that @opentelemetry/instrumentation's current code needs --
// confirmed by a real "doesn't provide an export named: 'logs'" error.
// 1.10.0 (what esm.sh gave our own top-level import by default, before
// any pinning) has it.
const API_VERSION = "1.10.0";
const API_DEP = `deps=@opentelemetry/api@${API_VERSION}`;

// Static `import` statements require a literal string specifier -- can't
// interpolate API_VERSION into one. Using dynamic import() everywhere
// instead, consistently, since it does accept an expression.
const { diag, DiagConsoleLogger, DiagLogLevel } = await import(
  `https://esm.sh/@opentelemetry/api@${API_VERSION}`
);

// OTel JS's internal diagnostic logger is a silent no-op by default --
// turning it on is the standard way to see WHY something silently isn't
// working, since by design it never surfaces as a normal thrown/visible
// error otherwise. WARN is enough once this is working; bump to DEBUG
// temporarily if something regresses.
diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.WARN);

// The ?deps= pin only goes on packages that actually touch OTel's global
// registry (setGlobalTracerProvider/setGlobalPropagator/setGlobalContextManager,
// or trace.getTracer()/context.active() reading from it) -- those MUST
// share one exact @opentelemetry/api instance with each other. Forcing it
// onto exporter-trace-otlp-http too (a package that never touches the
// global registry, it just serializes spans handed to it) caused a
// different real error: its own dependency chain needs `SeverityNumber`
// from @opentelemetry/api-logs, and the blanket override collided with
// that resolution. Leaving the exporter/resources/core/sdk-trace-base
// unpinned, since they don't need to share the registry instance.
const { WebTracerProvider } = await import(
  `https://esm.sh/@opentelemetry/sdk-trace-web?${API_DEP}`
);
const { BatchSpanProcessor } = await import(
  "https://esm.sh/@opentelemetry/sdk-trace-base"
);
const { OTLPTraceExporter } = await import(
  "https://esm.sh/@opentelemetry/exporter-trace-otlp-http"
);
const { registerInstrumentations } = await import(
  `https://esm.sh/@opentelemetry/instrumentation?${API_DEP}`
);
const { FetchInstrumentation } = await import(
  `https://esm.sh/@opentelemetry/instrumentation-fetch?${API_DEP}`
);
const { DocumentLoadInstrumentation } = await import(
  `https://esm.sh/@opentelemetry/instrumentation-document-load?${API_DEP}`
);
const { resourceFromAttributes } = await import(
  "https://esm.sh/@opentelemetry/resources"
);
const { W3CTraceContextPropagator } = await import(
  "https://esm.sh/@opentelemetry/core"
);

const provider = new WebTracerProvider({
  resource: resourceFromAttributes({ "service.name": "frontend" }),
  spanProcessors: [
    // Sends directly to the OTel Collector's OTLP/HTTP receiver, port 4318.
    // This is a genuinely cross-origin request (browser page is on :8000,
    // this is :4318) -- the Collector's receiver config has a matching
    // `cors` block allowing it. See otel-collector/config.yaml.
    new BatchSpanProcessor(
      new OTLPTraceExporter({ url: "http://localhost:4318/v1/traces" })
    ),
  ],
});

provider.register({
  propagator: new W3CTraceContextPropagator(),
});

registerInstrumentations({
  tracerProvider: provider,
  instrumentations: [
    // One span for the page load itself (navigation timing).
    new DocumentLoadInstrumentation(),
    // One span per fetch() call -- and critically, propagateTraceHeaderCorsUrls
    // tells it to attach the traceparent header on requests to our own
    // backend, so the browser's span becomes the PARENT of api-gateway's
    // server span for that same request, joining one trace across the
    // browser/backend boundary for the first time in this project.
    new FetchInstrumentation({
      propagateTraceHeaderCorsUrls: [/^http:\/\/localhost:8000\/.*/],
    }),
  ],
});
