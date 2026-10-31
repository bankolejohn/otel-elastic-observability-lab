# ADR-0002: Python/FastAPI, Postgres, Redis as the stack

Date: 2026-10-28
Status: Accepted

## Context

The user is a beginner in SRE/observability, not necessarily in the
language/stack. The stack itself isn't the lesson — OpenTelemetry, the
Collector, and Elasticsearch are. The stack should get out of the way.

## Decision

- **Python + FastAPI** for every backend service.
- **PostgreSQL** as the relational store (orders, inventory).
- **Redis** as a cache, to get a second, distinct dependency *type* (not
  just "another HTTP service" or "another database").
- **Plain HTML/JS** for the frontend (no build step, no framework).

## Alternatives considered

- **Node.js/Express.** Equally mature OTel support, but FastAPI's automatic
  OpenAPI docs and type-hint-driven validation reduce incidental complexity
  for a beginner reading the code later.
- **Go.** Excellent performance and OTel support, but explicit error
  handling and a compiled workflow add friction for someone focused on
  learning observability concepts, not Go.
- **A JS framework (React/Vue) for the frontend.** Would need a build step
  and adds no observability-learning value yet. Revisit only when we reach
  browser RUM instrumentation (Stage B/C), where instrumenting a plain
  `fetch()` call is just as valid a lesson as instrumenting a framework.

## Consequences

- Every service looks almost identical (FastAPI + SQLAlchemy/httpx/redis),
  which is good for a beginner (one pattern to learn, not four) but means
  this project under-teaches polyglot tracing (OTel across different
  languages). Acceptable: that's not this project's goal.
- Python's OpenTelemetry auto-instrumentation packages
  (`opentelemetry-instrumentation-fastapi`, `-httpx`, `-sqlalchemy`,
  `-redis`) are mature and require minimal manual span code, which keeps
  Stage B focused on concepts rather than SDK plumbing.

## Revisit when

If a later stage wants to demonstrate cross-language trace propagation,
add one service in a second language rather than converting the stack.
