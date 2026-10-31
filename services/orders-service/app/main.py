import json
import logging
import os

import httpx
import redis
from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel
from sqlalchemy import create_engine, text

# NOTE: when this service runs under `opentelemetry-instrument` (see the
# Dockerfile), OTEL_PYTHON_LOG_CORRELATION=true makes the logging
# instrumentation call logging.basicConfig() first, with a format that
# includes trace_id/span_id -- before this module is even imported. The
# basicConfig() call below is then a documented no-op (Python's logging
# module only honors the *first* basicConfig() call); it only takes effect
# if this app is ever run directly with plain `uvicorn`, without OTel
# wrapping it, so logging still works sensibly either way.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("orders-service")

# Manual instrumentation handles, used alongside the automatic instrumentation
# that opentelemetry-instrument already adds for fastapi/httpx/sqlalchemy/redis.
tracer = trace.get_tracer("orders-service.tracer")
meter = metrics.get_meter("orders-service.meter")

orders_created_counter = meter.create_counter(
    "orders.created",
    description="Number of orders successfully created",
    unit="1",
)
cache_lookup_counter = meter.create_counter(
    "orders.cache_lookup",
    description="Price cache lookups, by result (hit/miss)",
    unit="1",
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@localhost:5432/appdb")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8002")

engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=0, pool_timeout=5)
redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)

app = FastAPI(title="orders-service")


class OrderRequest(BaseModel):
    product_id: int
    quantity: int


def get_product_cached(product_id: int) -> dict:
    """Cache-aside lookup: Redis first, inventory-service on a miss (or if Redis is down).

    Wrapped in a manual span so this business-logic step shows up as its own
    node in the trace, nested under the automatic FastAPI server span and
    sibling to the automatic Redis/httpx client spans it triggers.
    """
    with tracer.start_as_current_span("get_product_cached") as span:
        span.set_attribute("product.id", product_id)
        cache_key = f"product:{product_id}"

        try:
            cached = redis_client.get(cache_key)
        except redis.RedisError as exc:
            logger.warning("Redis unavailable, falling back to inventory-service: %s", exc)
            cached = None

        if cached:
            logger.info("Cache hit for product %s", product_id)
            span.set_attribute("cache.hit", True)
            cache_lookup_counter.add(1, {"result": "hit"})
            return json.loads(cached)

        logger.info("Cache miss for product %s, calling inventory-service", product_id)
        span.set_attribute("cache.hit", False)
        cache_lookup_counter.add(1, {"result": "miss"})

        resp = httpx.get(f"{INVENTORY_SERVICE_URL}/products/{product_id}", timeout=5.0)
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Product not found")
        resp.raise_for_status()
        product = resp.json()

        try:
            redis_client.set(cache_key, json.dumps(product), ex=30)
        except redis.RedisError as exc:
            logger.warning("Failed to write product %s to cache: %s", product_id, exc)

        return product


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orders")
def create_order(req: OrderRequest):
    product = get_product_cached(req.product_id)

    # Stage G deliberately left this call uncaught, to practice diagnosing
    # an unclassified failure from telemetry alone (see
    # docs/stages/stage-g-chaos-engineering.md). Stage 2 deliberately adds
    # classification here instead -- now that the goal is sorting *known*
    # categories into the Streams hierarchy, not discovering an unknown one.
    try:
        reserve_resp = httpx.post(
            f"{INVENTORY_SERVICE_URL}/products/{req.product_id}/reserve",
            json={"quantity": req.quantity},
            timeout=5.0,
        )
    except httpx.TimeoutException as exc:
        current_span = trace.get_current_span()
        current_span.set_attribute("error.category", "query_timeout")
        current_span.set_status(Status(StatusCode.ERROR, "query_timeout"))
        logger.error(
            "Timed out waiting for inventory-service to reserve product %s: %s",
            req.product_id, exc, extra={"error.category": "query_timeout"},
        )
        raise HTTPException(status_code=504, detail="Inventory service timed out") from exc
    except httpx.RequestError as exc:
        current_span = trace.get_current_span()
        current_span.set_attribute("error.category", "unavailable")
        current_span.set_status(Status(StatusCode.ERROR, "unavailable"))
        logger.error(
            "inventory-service unreachable reserving product %s: %s",
            req.product_id, exc, extra={"error.category": "unavailable"},
        )
        raise HTTPException(status_code=503, detail="Inventory service unavailable") from exc

    if reserve_resp.status_code == 409:
        logger.warning("Order rejected, insufficient stock for product %s", req.product_id)
        raise HTTPException(status_code=409, detail="Insufficient stock")

    if reserve_resp.status_code >= 500:
        # inventory-service returns a structured {"message", "error_category"}
        # body for classified failures (see inventory-service/app/main.py) --
        # read it instead of letting raise_for_status() blow up uncaught and
        # lose that classification on the way up (that cascade is exactly
        # what Stage G found: a specific error degrading into a generic,
        # uninformative 500 by the time it reaches the caller).
        try:
            inventory_detail = reserve_resp.json().get("detail", {})
        except ValueError:
            inventory_detail = {}
        category = (
            inventory_detail.get("error_category", "unavailable")
            if isinstance(inventory_detail, dict)
            else "unavailable"
        )
        current_span = trace.get_current_span()
        current_span.set_attribute("error.category", category)
        current_span.set_status(Status(StatusCode.ERROR, category))
        logger.error(
            "inventory-service failed reserving product %s (%s): %s",
            req.product_id, category, inventory_detail, extra={"error.category": category},
        )
        raise HTTPException(
            status_code=503,
            detail={"message": "Inventory service error", "error_category": category},
        )

    reserve_resp.raise_for_status()

    total_cents = product["price_cents"] * req.quantity

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO orders.orders (product_id, quantity, total_cents, status) "
                "VALUES (:pid, :qty, :total, 'created') RETURNING order_id, created_at"
            ),
            {"pid": req.product_id, "qty": req.quantity, "total": total_cents},
        ).mappings().first()

    order = {
        "order_id": row["order_id"],
        "product_id": req.product_id,
        "quantity": req.quantity,
        "total_cents": total_cents,
        "status": "created",
        "created_at": row["created_at"].isoformat(),
    }
    orders_created_counter.add(1, {"product_id": str(req.product_id)})
    logger.info("Order created: %s", order)
    return order


@app.get("/orders")
def list_orders():
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT order_id, product_id, quantity, total_cents, status, created_at "
                "FROM orders.orders ORDER BY order_id DESC LIMIT 50"
            )
        ).mappings().all()
    return [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT order_id, product_id, quantity, total_cents, status, created_at "
                "FROM orders.orders WHERE order_id = :oid"
            ),
            {"oid": order_id},
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return {**dict(row), "created_at": row["created_at"].isoformat()}
