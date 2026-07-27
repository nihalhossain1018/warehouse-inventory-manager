-- Schema for the warehouse inventory database.
-- Loaded once at startup by db.py to create tables if they don't exist yet.

-- A physical spot on the warehouse floor, e.g. aisle A3, shelf S2, bin B7.
CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,   -- full human-readable id, e.g. "A3-S2-B7"
    aisle       TEXT NOT NULL,
    shelf       TEXT NOT NULL,
    bin         TEXT NOT NULL,
    capacity    INTEGER NOT NULL DEFAULT 5  -- max distinct products this location can hold
);

-- A distinct item that can be stored in the warehouse.
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    category    TEXT
);

-- How many units of a product are currently expected at a location.
-- One row per (product, location) pair; quantity is the system's "belief".
CREATE TABLE IF NOT EXISTS inventory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    location_id INTEGER NOT NULL REFERENCES locations(id),
    quantity    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (product_id, location_id)
);

-- An append-only audit trail: every time a quantity changes, why, and by how much.
-- This is what lets us answer "what happened to this product/location over time?"
CREATE TABLE IF NOT EXISTS movement_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    location_id     INTEGER NOT NULL REFERENCES locations(id),
    old_quantity    INTEGER NOT NULL,
    new_quantity    INTEGER NOT NULL,
    reason          TEXT NOT NULL,     -- "received", "shipped", "counted", "adjustment", ...
    discrepancy     INTEGER NOT NULL DEFAULT 0,  -- 1 if a reconcile found a mismatch, else 0
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
);
