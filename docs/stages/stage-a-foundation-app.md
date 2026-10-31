# Stage A — Foundation app (no telemetry yet)

Status: **Complete**
Related ADRs: [0001](../adr/0001-multi-service-topology.md), [0002](../adr/0002-tech-stack-choice.md), [0003](../adr/0003-synchronous-request-handling.md), [0004](../adr/0004-constrained-db-connection-pools.md), [0005](../adr/0005-redis-cache-aside-pricing.md), [0006](../adr/0006-frontend-co-hosted-on-gateway.md)

## What

A small full-stack "shop" application: a browser frontend, three backend
services, Postgres, and Redis — running locally under Docker Compose, with
no observability tooling at all yet.

```
browser
  |
  v
api-gateway  (:8000, serves the frontend + proxies /api/*)
  |
  v
orders-service  (:8001)
  |              \
  v               v
redis           inventory-service  (:8002)
(price cache)         |
  |                   v
  v               postgres (inventory schema)
postgres (orders schema)
```

## Why this exists before any telemetry

You can't meaningfully learn distributed tracing, log correlation, or
dependency-failure diagnosis against a single process or against a system
with nothing real happening in it. Stage A's only job is to produce a
system with:

1. **Real network boundaries** (ADR-0001) — a trace is only interesting
   once it crosses one.
2. **More than one dependency type** — an HTTP call to another service
   (inventory-service), a cache (Redis), and a database (Postgres) — so
   later chaos experiments can produce genuinely different failure
   signatures, not just "the one thing I can break."
3. **A trivially understandable business flow** (place an order) so that
   when we're staring at a trace waterfall in Stage E, the *telemetry* is
   the new thing to learn, not the business logic.

## Components

| Component | Port | Responsibility | Data store |
|---|---|---|---|
| `api-gateway` | 8000 | Serves frontend static files; single entry point; proxies `/api/*` to the other two services | — |
| `orders-service` | 8001 | Order placement logic: price lookup (cache-aside), stock reservation, order persistence | `postgres` (`orders` schema) |
| `inventory-service` | 8002 | Owns product + stock data | `postgres` (`inventory` schema) |
| `postgres` | 5432 | Relational storage, one instance, two schemas | — |
| `redis` | 6379 | Cache for product price/info, used by `orders-service` | — |

## Data flow: placing an order

This is the sequence that Stage B's tracing will eventually make visible
as a single connected trace:

1. Browser `POST /api/orders {product_id, quantity}` → **api-gateway**
2. api-gateway proxies to **orders-service** `POST /orders`
3. orders-service calls `get_product_cached(product_id)`:
   - checks Redis key `product:{id}`
   - **cache hit** → use cached price, done
   - **cache miss** (or Redis error) → `GET inventory-service:/products/{id}`, then write the result back to Redis with a 30s TTL
4. orders-service calls `POST inventory-service:/products/{id}/reserve {quantity}`
   - inventory-service runs `SELECT ... FOR UPDATE` on the product row, checks `stock >= quantity`, decrements stock, commits
   - insufficient stock → `409 Insufficient stock`, propagated back up through orders-service → api-gateway → browser
5. orders-service inserts a row into `orders.orders`, returns the order
6. api-gateway returns the order JSON to the browser; frontend refreshes the orders table and product list

## Database schema

```sql
inventory.products (product_id, name, price_cents, stock)
orders.orders      (order_id, product_id, quantity, total_cents, status, created_at)
```

Seeded with three products (Widget/Gadget/Gizmo) on first container start
via `db/init.sql`, mounted into Postgres's `docker-entrypoint-initdb.d/`.

## How to run

```bash
docker compose up --build
```

Open http://localhost:8000.

## How to verify

```bash
# 1. All three services report healthy
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
# each -> {"status":"ok"}

# 2. Seeded products are visible through the gateway
curl http://localhost:8000/api/products

# 3. Place an order (first time for this product -> Redis cache miss,
#    inventory-service gets called for the price)
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 2}'

# 4. Place another order for the same product within 30s
#    -> Redis cache HIT this time; confirm via container logs:
docker compose logs orders-service --tail 20
# look for: "Cache hit for product 1"

# 5. Confirm stock was actually decremented
curl http://localhost:8000/api/products

# 6. Try to oversell -> expect 409
curl -i -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 3, "quantity": 999}'
# -> HTTP/1.1 409 Conflict  {"detail":"Insufficient stock"}
```

All six checks were run against the real stack on 2026-10-28 and passed:
health checks OK, product list returned 3 seeded products, order #1 showed
a cache miss + inventory-service call in the logs, order #2 for the same
product showed a cache hit, stock dropped 50→48→47 across the two orders,
and the oversell attempt returned exactly `409 {"detail":"Insufficient
stock"}`.

## Troubleshooting log

**Docker build intermittently failed resolving `greenlet` (a SQLAlchemy
dependency) with `No matching distribution found ... (from versions:
none)`.** This looked like a missing package, but `docker run --rm
python:3.11-slim pip index versions greenlet` succeeded instantly and
listed dozens of available versions — so the package was never actually
missing. The failure was a transient hiccup in pip's dependency resolver
hitting PyPI during the `docker compose build` network session (likely a
dropped connection treated as "no versions" instead of a hard network
error). Fix was simply retrying `docker compose up --build`; the second
attempt completed cleanly. **Lesson:** a pip resolver error that claims a
version doesn't exist isn't proof the version doesn't exist — check `pip
index versions <pkg>` directly before changing pinned versions or chasing
a phantom compatibility issue.

## What's next

Stage B adds OpenTelemetry SDKs to each service and gets traces/logs
printing to the console — see `docs/stages/stage-b-*.md` once that stage
starts.
