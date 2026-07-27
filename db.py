# Data layer: the only file that knows SQL or touches the SQLite file directly.
# Every function here does one table operation and returns plain dicts/rows.
# No business rules live here (e.g. "can't have negative inventory") - that's
# inventory.py's job. Keeping this separate means if we ever swap SQLite for
# another database, only this file has to change.

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "warehouse.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row  # lets us access columns by name, e.g. row["sku"]
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)


def _migrate(conn):
    """Add columns introduced after a database already existed on disk.
    CREATE TABLE IF NOT EXISTS in schema.sql only covers brand-new databases."""
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(locations)")]
    if "capacity" not in columns:
        conn.execute("ALTER TABLE locations ADD COLUMN capacity INTEGER NOT NULL DEFAULT 5")


# ---------- products ----------

def insert_product(sku, name, category):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO products (sku, name, category) VALUES (?, ?, ?)",
            (sku, name, category),
        )
        return cursor.lastrowid


def get_product_by_sku(sku):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        return dict(row) if row else None


def list_products():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
        return [dict(row) for row in rows]


def count_product_activity(product_id):
    """How many inventory or movement-log rows reference this product.
    Zero means it's never actually been placed anywhere - safe to delete."""
    with get_connection() as conn:
        inventory_count = conn.execute(
            "SELECT COUNT(*) FROM inventory WHERE product_id = ?", (product_id,)
        ).fetchone()[0]
        movement_count = conn.execute(
            "SELECT COUNT(*) FROM movement_log WHERE product_id = ?", (product_id,)
        ).fetchone()[0]
        return inventory_count + movement_count


def delete_product(product_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


# ---------- locations ----------

def insert_location(code, aisle, shelf, bin_, capacity):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO locations (code, aisle, shelf, bin, capacity) VALUES (?, ?, ?, ?, ?)",
            (code, aisle, shelf, bin_, capacity),
        )
        return cursor.lastrowid


def get_location_by_code(code):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM locations WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None


def list_locations():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM locations ORDER BY code").fetchall()
        return [dict(row) for row in rows]


def count_location_activity(location_id):
    """How many inventory or movement-log rows reference this location.
    Zero means it's never actually held anything - safe to delete."""
    with get_connection() as conn:
        inventory_count = conn.execute(
            "SELECT COUNT(*) FROM inventory WHERE location_id = ?", (location_id,)
        ).fetchone()[0]
        movement_count = conn.execute(
            "SELECT COUNT(*) FROM movement_log WHERE location_id = ?", (location_id,)
        ).fetchone()[0]
        return inventory_count + movement_count


def delete_location(location_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))


def list_location_capacity_info():
    """Every location plus how many distinct products it currently holds
    and which categories those products belong to - the data auto-placement
    needs to decide where a product should go."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, code, aisle, shelf, bin, capacity FROM locations ORDER BY code"
        ).fetchall()
        locations = []
        for row in rows:
            used_slots = conn.execute(
                "SELECT COUNT(*) FROM inventory WHERE location_id = ? AND quantity > 0",
                (row["id"],),
            ).fetchone()[0]
            categories = conn.execute(
                """
                SELECT DISTINCT products.category
                FROM inventory
                JOIN products ON products.id = inventory.product_id
                WHERE inventory.location_id = ? AND inventory.quantity > 0
                      AND products.category IS NOT NULL
                """,
                (row["id"],),
            ).fetchall()
            locations.append({
                "id": row["id"],
                "code": row["code"],
                "aisle": row["aisle"],
                "shelf": row["shelf"],
                "bin": row["bin"],
                "capacity": row["capacity"],
                "used_slots": used_slots,
                "categories": [c["category"] for c in categories],
            })
        return locations


# ---------- inventory ----------

def get_inventory(product_id, location_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM inventory WHERE product_id = ? AND location_id = ?",
            (product_id, location_id),
        ).fetchone()
        return dict(row) if row else None


def upsert_inventory(product_id, location_id, quantity):
    """Set the quantity for a (product, location) pair, creating the row if needed."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM inventory WHERE product_id = ? AND location_id = ?",
            (product_id, location_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE inventory SET quantity = ? WHERE id = ?",
                (quantity, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO inventory (product_id, location_id, quantity) VALUES (?, ?, ?)",
                (product_id, location_id, quantity),
            )


def list_inventory_by_product(product_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT inventory.*, locations.code AS location_code
            FROM inventory
            JOIN locations ON locations.id = inventory.location_id
            WHERE product_id = ?
            ORDER BY locations.code
            """,
            (product_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_inventory_by_location(location_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT inventory.*, products.sku AS product_sku, products.name AS product_name
            FROM inventory
            JOIN products ON products.id = inventory.product_id
            WHERE location_id = ?
            ORDER BY products.sku
            """,
            (location_id,),
        ).fetchall()
        return [dict(row) for row in rows]


# ---------- movement log ----------

def insert_movement(product_id, location_id, old_quantity, new_quantity, reason, discrepancy=0):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO movement_log
                (product_id, location_id, old_quantity, new_quantity, reason, discrepancy)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (product_id, location_id, old_quantity, new_quantity, reason, discrepancy),
        )
        return cursor.lastrowid


def list_movements_by_product(product_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT movement_log.*, locations.code AS location_code
            FROM movement_log
            JOIN locations ON locations.id = movement_log.location_id
            WHERE product_id = ?
            ORDER BY timestamp DESC
            """,
            (product_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_movements_by_location(location_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT movement_log.*, products.sku AS product_sku, products.name AS product_name
            FROM movement_log
            JOIN products ON products.id = movement_log.product_id
            WHERE location_id = ?
            ORDER BY timestamp DESC
            """,
            (location_id,),
        ).fetchall()
        return [dict(row) for row in rows]


# ---------- dashboard summary ----------

def count_products():
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]


def count_locations():
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0]


def count_discrepancies():
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM movement_log WHERE discrepancy = 1"
        ).fetchone()[0]


def count_movements():
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM movement_log").fetchone()[0]


def list_recent_movements(limit=8):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT movement_log.*, products.sku AS product_sku, products.name AS product_name,
                   locations.code AS location_code
            FROM movement_log
            JOIN products ON products.id = movement_log.product_id
            JOIN locations ON locations.id = movement_log.location_id
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
