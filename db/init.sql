-- Schema for the observability demo shop.
-- Two logical areas living in one Postgres instance, each owned by its own service:
--   inventory.* -> owned by inventory-service
--   orders.*    -> owned by orders-service

CREATE SCHEMA IF NOT EXISTS inventory;
CREATE SCHEMA IF NOT EXISTS orders;

CREATE TABLE IF NOT EXISTS inventory.products (
    product_id   SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    price_cents  INTEGER NOT NULL,
    stock        INTEGER NOT NULL
);

INSERT INTO inventory.products (name, price_cents, stock) VALUES
    ('Widget', 999, 50),
    ('Gadget', 1999, 30),
    ('Gizmo', 4999, 10)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS orders.orders (
    order_id     SERIAL PRIMARY KEY,
    product_id   INTEGER NOT NULL,
    quantity     INTEGER NOT NULL,
    total_cents  INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'created',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
