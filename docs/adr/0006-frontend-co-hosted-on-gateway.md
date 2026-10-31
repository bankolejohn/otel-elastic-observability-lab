# ADR-0006: Frontend served as static files from api-gateway

Date: 2026-10-28
Status: Accepted

## Context

"Full-stack" implies a browser-facing frontend, not just backend services.
The frontend needs to call the backend without hitting CORS issues, and
without adding a 5th container just to serve static files in Stage A.

## Decision

`api-gateway` mounts a `static/` directory (plain HTML/CSS/JS, no build
step) at `/`, registered *after* the `/api/*` and `/health` routes so it
doesn't shadow them. The browser and the API it calls share the same
origin (`http://localhost:8000`).

## Alternatives considered

- **Separate frontend container (e.g. nginx or a dev server) on its own
  port.** More realistic (frontend and backend are usually deployed
  separately), but introduces cross-origin requests, which means CORS
  configuration — extra complexity with no payoff in Stage A. It will
  become relevant in Stage C, when the browser needs to export OTel data
  directly to the Collector (a genuinely different origin), so CORS isn't
  avoided forever, just deferred to where it's actually the lesson.
- **Server-rendered templates (Jinja2) instead of a static SPA-lite page.**
  No real benefit here since the page is simple and mostly makes `fetch()`
  calls; plain static files are more transparent for instrumenting with
  OTel Web SDK later.

## Consequences

- One fewer moving part in Stage A.
- When we add browser-side OTel instrumentation, exporting traces from the
  browser to the Collector *will* cross an origin boundary (browser page
  on :8000 → Collector on its own port) — that's the point at which we'll
  need to revisit CORS, deliberately, as part of that stage's lesson.

## Revisit when

Stage C/D, when wiring the browser's OTel exporter to the Collector.
