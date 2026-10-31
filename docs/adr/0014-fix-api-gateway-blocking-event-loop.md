# ADR-0014: Fixed a real bug: api-gateway's `async def` endpoint blocking on a sync HTTP call

Date: 2026-10-30
Status: Accepted

## Context

While testing the `pool_exhausted` chaos mode (firing many concurrent
order requests to overwhelm inventory-service's 5-connection DB pool),
requests instead came back fully serialized -- one at a time, evenly
spaced ~3.1s apart -- regardless of which product they targeted.
Bisected by calling each service directly, one hop closer at a time:

- inventory-service directly, 2 different products: ran in parallel (~3.0s each).
- orders-service directly, 2 different products: ran in parallel (~3.2s each).
- **api-gateway**, 2 different products: did **not** run in parallel --
  one request waited for the other to finish entirely (3.1s then 6.2s).

The cause: `api-gateway/app/main.py`'s `/api/orders` endpoint was
declared `async def create_order(request: Request)`, but its body called
the *synchronous* `httpx.post(...)` -- a blocking network call -- directly
inside that async function. A blocking call inside `async def` blocks the
entire event loop, not just that one request's coroutine, so **every**
concurrent request to this one endpoint serialized, independent of
product, independent of inventory-service's DB pool entirely. This isn't
one of this project's deliberate landmines (ADR-0003, ADR-0004) -- it was
an unintentional bug, and it was actively masking the chaos experiment
Stage G was trying to run.

## Decision

Changed `create_order` to a plain `def` (sync) endpoint taking a Pydantic
`OrderRequest` model, matching the pattern already used by every other
endpoint in this codebase (ADR-0003) and by every other endpoint in this
same file. No more `async`/`await request.json()`.

## Alternatives considered

- **Switch to `httpx.AsyncClient` and keep `async def`.** The "more
  correct" production fix for a genuinely async service, but
  inconsistent with ADR-0003's deliberate, project-wide choice to keep
  everything synchronous for simplicity. Introducing async here just to
  patch one endpoint would mean two different concurrency models in one
  small codebase for no real benefit.
- **Leave it as-is and document it as a known landmine, like the
  undersized connection pools.** Rejected -- the undersized pools are
  *useful* landmines (they exist specifically to make a real lesson
  possible later). This bug provided no such value; it just hid the
  lesson `pool_exhausted` mode was built to teach. Masking one chaos
  experiment with an unrelated, accidental bug isn't a lesson worth
  preserving on purpose.

## Consequences

- Verified fix directly: the same 2-concurrent-request, 2-different-
  product test that showed `3.1s then 6.2s` before the fix now shows
  `3.2s and 3.3s` (genuinely parallel) after it.
- With the real bottleneck removed, the `pool_exhausted` chaos test
  then worked as originally intended: firing 20 concurrent requests
  produced 5 immediate successes and 15 requests failing with a real
  `QueuePool limit of size 5 overflow 0 reached, connection timed out,
  timeout 5.00` error -- see the Stage G doc.

## Revisit when

If any other endpoint is ever written as `async def`, audit it
specifically for synchronous blocking calls inside it -- this exact
mistake is easy to reintroduce and easy to miss in code review, since
the code runs fine under light, non-concurrent load and only reveals
itself under genuine concurrency.
