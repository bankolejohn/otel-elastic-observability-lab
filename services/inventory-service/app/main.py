import logging
import os

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from app import chaos

# See the identical comment in orders-service/app/main.py: this basicConfig()
# call is a documented no-op when run under opentelemetry-instrument with
# OTEL_PYTHON_LOG_CORRELATION=true (that instrumentation's own basicConfig()
# call wins, and injects trace_id/span_id into the format instead).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("inventory-service")

tracer = trace.get_tracer("inventory-service.tracer")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@localhost:5432/appdb")

# pool_size/max_overflow are deliberately small and fixed -- this is exactly
# the knob Stage G uses to simulate "pool exhausted" errors on purpose.
#
# pool_timeout is deliberately LOWER than orders-service's 5.0s httpx
# timeout to this service's /reserve endpoint (see orders-service/app/main.py),
# with a real margin (3s vs 5s), not an accident. Stage G and Stage 2 both
# found that when these two timeouts were numerically equal, a single
# pool-exhaustion event could race and get classified as query_timeout
# instead, depending on which side's clock fired first (see ADR-0015,
# ADR-0018). Keeping the callee's own timeout clearly shorter than the
# caller's means inventory-service's own, more specific error wins the
# race reliably, instead of leaving it to chance.
engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=0, pool_timeout=3)

app = FastAPI(title="inventory-service")


class ReserveRequest(BaseModel):
    quantity: int


class ChaosRequest(BaseModel):
    mode: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chaos")
def get_chaos():
    return {"mode": chaos.get_mode(), "valid_modes": chaos.VALID_MODES}


@app.post("/chaos")
def set_chaos(req: ChaosRequest):
    try:
        new_mode = chaos.set_mode(req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"mode": new_mode}


@app.get("/products")
def list_products():
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT product_id, name, price_cents, stock FROM inventory.products ORDER BY product_id")
        ).mappings().all()
    logger.info("Listed %d products", len(rows))
    return [dict(r) for r in rows]


def _classify_operational_error(exc: OperationalError) -> str:
    """Distinguish "we tried to connect and were actively refused" (our
    deliberate connection_failed chaos mode, pointed at a dead port) from
    "something else went wrong talking to the database" (e.g. the DB
    process itself was stopped mid-connection) -- the article's
    connection_failed and unavailable categories, told apart by content,
    not by which chaos mode happened to be active."""
    return "connection_failed" if "connection refused" in str(exc).lower() else "unavailable"


@app.get("/products/{product_id}")
def get_product(product_id: int):
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT product_id, name, price_cents, stock FROM inventory.products WHERE product_id = :pid"),
                {"pid": product_id},
            ).mappings().first()
    except SATimeoutError as exc:
        logger.error(
            "Pool exhausted getting product %s: %s", product_id, exc,
            extra={"error.category": "pool_exhausted"},
        )
        raise HTTPException(
            status_code=503,
            detail={"message": "Database pool exhausted", "error_category": "pool_exhausted"},
        ) from exc
    except OperationalError as exc:
        category = _classify_operational_error(exc)
        logger.error(
            "DB error (%s) getting product %s: %s", category, product_id, exc,
            extra={"error.category": category},
        )
        raise HTTPException(
            status_code=503,
            detail={"message": f"Database {category.replace('_', ' ')}", "error_category": category},
        ) from exc

    if row is None:
        logger.warning("Product %s not found", product_id)
        raise HTTPException(status_code=404, detail="Product not found")
    return dict(row)


@app.post("/products/{product_id}/reserve")
def reserve_product(product_id: int, req: ReserveRequest):
    # Manual span around the whole reserve transaction: this is the exact
    # "DB access layer" step the reference article's error categories
    # (query_timeout, connection_failed, pool_exhausted, unavailable) are
    # about, so it's worth being able to see it as its own span later,
    # separate from the automatic SQLAlchemy client spans nested inside it.
    mode = chaos.get_mode()
    with tracer.start_as_current_span("reserve_stock") as span:
        span.set_attribute("inventory.product_id", product_id)
        span.set_attribute("inventory.quantity_requested", req.quantity)
        if mode != "none":
            span.set_attribute("chaos.mode", mode)

        # connection_failed: use a connection to a port nothing listens on,
        # instead of the real pool -- everything else below is identical.
        active_engine = chaos.get_bad_engine(DATABASE_URL) if mode == "connection_failed" else engine

        try:
            with active_engine.begin() as conn:
                if mode == "slow":
                    # Succeeds, just slowly -- under orders-service's 5s
                    # httpx timeout, so the caller still gets a real answer.
                    conn.execute(text("SELECT pg_sleep(2)"))
                elif mode == "query_timeout":
                    # Exceeds orders-service's 5s httpx timeout -- the
                    # caller gives up and reports failure, but this request
                    # keeps running and WILL still commit below. A real,
                    # common distributed-systems trap: the caller's view of
                    # "it failed" and the callee's view of "it succeeded"
                    # disagree. See the Stage G doc for how to diagnose this.
                    conn.execute(text("SELECT pg_sleep(8)"))
                elif mode == "pool_exhausted":
                    # Holds this connection open well past pool_timeout (3s,
                    # see the engine comment above); with pool_size=5/
                    # max_overflow=0 (ADR-0004), a handful of concurrent
                    # requests like this one will exhaust the pool -- the
                    # FAILURE shows up on whichever *other* concurrent
                    # request can't get a connection, not necessarily this
                    # one. 4s hold vs 3s pool_timeout is a deliberate
                    # margin so a queued waiter reliably times out instead
                    # of narrowly squeaking through.
                    conn.execute(text("SELECT pg_sleep(4)"))

                row = conn.execute(
                    text("SELECT stock FROM inventory.products WHERE product_id = :pid FOR UPDATE"),
                    {"pid": product_id},
                ).mappings().first()
                if row is None:
                    logger.warning("Reserve failed, product %s not found", product_id)
                    span.set_attribute("inventory.result", "not_found")
                    raise HTTPException(status_code=404, detail="Product not found")
                if row["stock"] < req.quantity:
                    logger.warning(
                        "Insufficient stock for product %s: have %d, need %d",
                        product_id, row["stock"], req.quantity,
                    )
                    span.set_attribute("inventory.result", "insufficient_stock")
                    span.set_attribute("inventory.stock_available", row["stock"])
                    raise HTTPException(status_code=409, detail="Insufficient stock")
                conn.execute(
                    text("UPDATE inventory.products SET stock = stock - :qty WHERE product_id = :pid"),
                    {"qty": req.quantity, "pid": product_id},
                )
                new_stock = row["stock"] - req.quantity
        except SATimeoutError as exc:
            span.set_attribute("error.category", "pool_exhausted")
            span.set_status(Status(StatusCode.ERROR, "pool_exhausted"))
            span.record_exception(exc)
            logger.error(
                "Pool exhausted reserving product %s: %s", product_id, exc,
                extra={"error.category": "pool_exhausted"},
            )
            raise HTTPException(
                status_code=503,
                detail={"message": "Database pool exhausted", "error_category": "pool_exhausted"},
            ) from exc
        except OperationalError as exc:
            category = _classify_operational_error(exc)
            span.set_attribute("error.category", category)
            span.set_status(Status(StatusCode.ERROR, category))
            span.record_exception(exc)
            logger.error(
                "DB error (%s) reserving product %s: %s", category, product_id, exc,
                extra={"error.category": category},
            )
            raise HTTPException(
                status_code=503,
                detail={"message": f"Database {category.replace('_', ' ')}", "error_category": category},
            ) from exc

        span.set_attribute("inventory.result", "reserved")
        span.set_attribute("inventory.remaining_stock", new_stock)
        logger.info("Reserved %d of product %s, remaining stock %d", req.quantity, product_id, new_stock)
        return {"product_id": product_id, "reserved": req.quantity, "remaining_stock": new_stock}
