import logging
import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("api-gateway")

ORDERS_SERVICE_URL = os.getenv("ORDERS_SERVICE_URL", "http://localhost:8001")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8002")

app = FastAPI(title="api-gateway")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/products")
def get_products():
    try:
        resp = httpx.get(f"{INVENTORY_SERVICE_URL}/products", timeout=5.0)
    except httpx.RequestError as exc:
        logger.error("inventory-service unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="inventory-service unavailable")
    resp.raise_for_status()
    return resp.json()


class OrderRequest(BaseModel):
    product_id: int
    quantity: int


@app.post("/api/orders")
def create_order(order: OrderRequest):
    try:
        resp = httpx.post(f"{ORDERS_SERVICE_URL}/orders", json=order.model_dump(), timeout=10.0)
    except httpx.RequestError as exc:
        logger.error("orders-service unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="orders-service unavailable")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "error"))
    return resp.json()


@app.get("/api/orders")
def get_orders():
    try:
        resp = httpx.get(f"{ORDERS_SERVICE_URL}/orders", timeout=5.0)
    except httpx.RequestError as exc:
        logger.error("orders-service unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="orders-service unavailable")
    resp.raise_for_status()
    return resp.json()


# Mounted last so it never shadows the /api/* and /health routes above.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
