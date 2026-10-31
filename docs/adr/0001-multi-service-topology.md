# ADR-0001: Multi-service topology instead of a monolith

Date: 2026-10-28
Status: Accepted

## Context

The end goal of this project is to learn distributed tracing, log-to-trace
correlation, and dependency-failure diagnosis. None of that exists in a
single-process application — a trace is only interesting when it crosses a
process or network boundary, and "dependency failure" only means something
if there's an actual, separate dependency that can fail independently of
the caller.

## Decision

Built the app as four separate runtime components instead of one:

- `api-gateway` — single entry point, serves the frontend, proxies to
  orders-service / inventory-service
- `orders-service` — order placement business logic
- `inventory-service` — product/stock data owner
- `postgres` + `redis` — shared-nothing data stores, one used by each
  relevant service

A request to place an order genuinely crosses 4 network hops:
`browser → api-gateway → orders-service → redis` (or `→ inventory-service →
postgres`) `→ inventory-service (reserve) → postgres (orders insert)`.

## Alternatives considered

- **Single FastAPI app with internal modules.** Simpler to run, but there's
  no network boundary to trace across — every "span" would just be a
  function call in the same process. Defeats the purpose of Stage B.
  Monolith first, split later would have meant redoing the lesson.
- **A large, realistic number of microservices (5+).** More faithful to a
  "production" topology, but adds setup/debugging overhead disproportionate
  to the learning goal at this stage. Kept it to the minimum number of
  services that still produces a genuine multi-hop, multi-dependency-type
  trace.

## Consequences

- More docker-compose services, more Dockerfiles, more inter-service HTTP
  calls to get wrong (timeouts, retries, service discovery by DNS name).
- In exchange: a trace through this app will show 3 real services, a cache
  dependency, and a database dependency — enough shape to make distributed
  tracing, service maps, and dependency-failure diagnosis meaningful in
  Stage B/E/G without needing a bigger, harder-to-reason-about system.

## Revisit when

If a future stage needs a messaging/queue dependency (e.g. for async
processing failure modes), add a service rather than retrofitting one of
the existing three.
