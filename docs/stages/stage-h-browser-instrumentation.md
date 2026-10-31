# Stage H — Browser instrumentation (RUM)

Status: **Complete**
Related ADRs: [0019](../adr/0019-browser-instrumentation-dependency-pinning.md)

This is the first of several post-completion extensions, picked up after
the originally-scoped roadmap (Stages A-G, 2) finished. See `README.md`
for how this fits into the overall plan.

## What

The frontend (`services/api-gateway/static/`) is now instrumented with
the OpenTelemetry Web SDK — document-load timing, automatic spans for
every `fetch()` call, and trace context propagated to the backend, so a
browser interaction and everything it triggers server-side now share one
trace. This was the one piece of "full-stack" this project had never
actually touched; every prior stage instrumented the backend only.

## Why

Flagged explicitly back in ADR-0006 (Stage A) as deliberately deferred,
specifically because it introduces a genuine cross-origin request
(browser page on :8000, Collector on :4318) and because OpenTelemetry's
own documentation describes browser instrumentation as "experimental
and mostly unspecified." Both warnings turned out to be accurate —
getting this working took five real, sequential bugs, each confirmed
live in a browser, not guessed from documentation.

## How it works

See ADR-0019 for the full account of all five bugs and fixes. Summary of
what `otel-web.js` actually does:

1. Pins `@opentelemetry/api` to an exact version, and forces only the
   packages that touch OTel's global registry (`sdk-trace-web`,
   `instrumentation`, `instrumentation-fetch`,
   `instrumentation-document-load`) to share that exact version via
   esm.sh's `?deps=` parameter — not every package, since that broke a
   different, unrelated dependency resolution.
2. Enables OTel's diagnostic logger permanently (silent by default,
   which is exactly what hid the registry-mismatch bug in the first
   place).
3. Builds a `WebTracerProvider` with a `BatchSpanProcessor` exporting to
   the Collector's OTLP/HTTP endpoint (`http://localhost:4318/v1/traces`).
4. Registers `DocumentLoadInstrumentation` (page load spans) and
   `FetchInstrumentation` (one span per `fetch()` call), with
   `propagateTraceHeaderCorsUrls` matching our own backend origin so the
   `traceparent` header actually gets attached to our API calls.

The Collector's OTLP HTTP receiver (`otel-collector/config.yaml`) has a
`cors` block explicitly allowing `http://localhost:8000` — without it,
the browser's preflight `OPTIONS` request would be rejected before any
of the above mattered.

## How to verify

```bash
# 1. CORS preflight works
curl -i -X OPTIONS http://localhost:4318/v1/traces \
  -H "Origin: http://localhost:8000" \
  -H "Access-Control-Request-Method: POST"
# -> 204, Access-Control-Allow-Origin: http://localhost:8000

# 2. Place an order through the actual browser UI, then find the frontend's
#    spans in Elasticsearch:
curl -H "Authorization: ApiKey $ELASTIC_API_KEY" -H "Content-Type: application/json" \
  "$ELASTIC_ENDPOINT/traces-generic.otel-default/_search" \
  -d '{"query":{"term":{"resource.attributes.service.name":"frontend"}},"sort":[{"@timestamp":"desc"}],"size":5}'

# 3. Take one trace_id from that result and pull every span in it, to
#    confirm the frontend span is the root (no parent_span_id) and that
#    api-gateway's own server span's parent_span_id points at it.
```

**Actually run on 2026-10-31/11-01:** 82 frontend spans landed in a
10-minute window, including real `resourceFetch` spans (document-load
instrumentation reading the Navigation Timing API) and `GET`/`POST`
spans (fetch instrumentation). Pulled every span for one order's
`trace_id` (`13a691d3638da7c3a199c78240d32d99`) and got the complete
chain, 29 spans, one trace:

```
frontend            POST                                      (root, no parent)
  api-gateway       POST /api/orders                           <- parent: frontend's POST
    api-gateway     POST (client call to orders-service)
      orders-service POST /orders
        orders-service get_product_cached
          orders-service GET (redis)
          orders-service GET (httpx to inventory-service)
            inventory-service GET /products/{id}
              inventory-service connect / SELECT appdb / http send spans
        orders-service SET (redis cache write)
        orders-service POST (httpx to inventory-service /reserve)
          inventory-service POST /products/{id}/reserve
            inventory-service reserve_stock
              inventory-service connect / SELECT appdb / UPDATE appdb
        orders-service connect / INSERT appdb
```

The frontend's own `POST` span has no `parent_span_id` at all (it's the
true root of the trace) and is the direct parent of api-gateway's
`POST /api/orders` server span. This is the first time in the project a
trace has genuinely started in the browser.

## Troubleshooting log

All five bugs, encountered in this exact order, each confirmed by a
specific real error (not inferred):

1. `Uncaught SyntaxError: ... doesn't provide an export named: 'Resource'`
   — `@opentelemetry/resources` v2.x removed the `Resource` class.
2. `TypeError: ... addSpanProcessor is not a function` — removed in
   favor of a constructor option.
3. **The silent one.** Console was completely clean, zero errors, but
   also zero network requests to the Collector ever happened — not even
   a failed/blocked one. A raw manual `fetch()` to the same URL from the
   Console worked fine (ruling out CORS/network). The actual cause only
   became visible after enabling `DiagConsoleLogger`: `sdk-trace-web` had
   resolved its own separate copy of `@opentelemetry/api` (v1.9.1),
   different from the one imported directly in `otel-web.js` (v1.10.0),
   so the global tracer/propagator registry `provider.register()` wrote
   to wasn't the one instrumentation code was reading from. OTel's
   `diag` logger is a silent no-op by default — this is precisely the
   failure mode that silence hides.
4. Fixing #3 by pinning `@opentelemetry/api` on *every* import broke
   `exporter-trace-otlp-http`: `doesn't provide an export named:
   'SeverityNumber'` — its own dependency chain needed that from the
   separate `@opentelemetry/api-logs` package, and the blanket pin
   collided with it.
5. Narrowing the pin to only the registry-touching packages (fixing #4)
   surfaced one more: `doesn't provide an export named: 'logs'` — the
   specific version pinned (1.9.1) was too old for what
   `@opentelemetry/instrumentation`'s current code expects. Switching to
   1.10.0 resolved both #3 and #5 simultaneously.

**Meta-lesson:** step 3 is the one worth remembering longest. "No error,
but also nothing happens" in OpenTelemetry JS should immediately prompt
enabling the diagnostic logger, not more staring at a clean Console —
the silence itself was the bug's signature.

## What's next

Continuing the post-completion extension list from where this left off:
live-creating the three alert rules (needs the Kibana endpoint), and a
real Kibana dashboard, now that there's genuinely interesting
browser-to-backend trace data to visualize.
