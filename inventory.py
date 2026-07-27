# Business logic layer: the rules of how inventory is allowed to change.
# app.py (the web layer) calls into these functions instead of touching db.py
# directly, so validation (e.g. "no negative inventory") lives in exactly one
# place regardless of how many web routes end up calling it.

import random

import db

VALID_ASSIGN_REASONS = {"received", "shipped", "adjustment"}

# Excludes characters that are easy to misread on a printed label (0/O, 1/I/L).
SKU_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class InventoryError(Exception):
    """Raised when a request breaks a business rule (bad SKU, negative qty, etc)."""


# ---------- products & locations ----------

def generate_unique_sku():
    """Generate a random SKU that doesn't collide with an existing one.
    Barcode scanners just need something unique and short - the letters
    don't need to mean anything, unlike a location code."""
    for _ in range(20):
        sku = "SKU-" + "".join(random.choices(SKU_ALPHABET, k=8))
        if not db.get_product_by_sku(sku):
            return sku
    raise InventoryError("Could not generate a unique SKU, please try again.")


def add_product(sku, name, category):
    sku = sku or generate_unique_sku()
    if db.get_product_by_sku(sku):
        raise InventoryError(f"Product with SKU '{sku}' already exists.")
    if not name:
        raise InventoryError("Name is required.")
    db.insert_product(sku, name, category)
    return sku


def delete_product(sku):
    """Remove a product outright, but only if it's never actually been used -
    no inventory and no movement history. This keeps the audit trail intact
    for anything that's had real activity; use Assign Inventory to zero out
    a product's stock first if you want it gone from the floor."""
    product = db.get_product_by_sku(sku)
    if not product:
        raise InventoryError(f"No product with SKU '{sku}'.")
    if db.count_product_activity(product["id"]) > 0:
        raise InventoryError(
            f"Can't delete {sku} - it already has inventory or movement history. "
            "Zero out its inventory via Assign Inventory first if you need it gone."
        )
    db.delete_product(product["id"])


def add_location(aisle, shelf, bin_, capacity=5):
    if not aisle or not shelf or not bin_:
        raise InventoryError("Aisle, shelf, and bin are all required.")
    if capacity < 1:
        raise InventoryError("Capacity must be at least 1.")
    code = f"{aisle}-{shelf}-{bin_}"
    if db.get_location_by_code(code):
        raise InventoryError(f"Location '{code}' already exists.")
    db.insert_location(code, aisle, shelf, bin_, capacity)
    return code


def delete_location(code):
    """Remove a location outright, but only if it's never actually held
    anything - no inventory and no movement history. Same rule as deleting
    a product: real activity stays in the audit trail permanently."""
    location = db.get_location_by_code(code)
    if not location:
        raise InventoryError(f"No location '{code}'.")
    if db.count_location_activity(location["id"]) > 0:
        raise InventoryError(
            f"Can't delete {code} - it already has inventory or movement history. "
            "Zero out its inventory via Assign Inventory first if you need it gone."
        )
    db.delete_location(location["id"])


# ---------- assigning inventory ----------

def assign_inventory(sku, location_code, quantity_change, reason):
    """Record a movement (receiving, shipping, or a manual adjustment) and
    update the inventory quantity for that product+location accordingly."""
    if reason not in VALID_ASSIGN_REASONS:
        raise InventoryError(f"Reason must be one of {sorted(VALID_ASSIGN_REASONS)}.")

    product = db.get_product_by_sku(sku)
    if not product:
        raise InventoryError(f"No product with SKU '{sku}'.")

    location = db.get_location_by_code(location_code)
    if not location:
        raise InventoryError(f"No location '{location_code}'.")

    current = db.get_inventory(product["id"], location["id"])
    old_quantity = current["quantity"] if current else 0
    new_quantity = old_quantity + quantity_change

    if new_quantity < 0:
        raise InventoryError(
            f"That would leave {new_quantity} units at {location_code} - inventory can't go negative."
        )

    db.upsert_inventory(product["id"], location["id"], new_quantity)
    db.insert_movement(product["id"], location["id"], old_quantity, new_quantity, reason)


# ---------- auto-placement ----------

def suggest_location_for_sku(sku):
    """Pick where a product should go, in order of preference:
    1. A location that already stocks this exact SKU (consolidate, not spread out).
    2. A location that already stocks the same category and has an open slot.
    3. Any location with an open slot, preferring the one with the most room.
    Returns (location_code, reason_text)."""
    product = db.get_product_by_sku(sku)
    if not product:
        raise InventoryError(f"No product with SKU '{sku}'.")

    for row in db.list_inventory_by_product(product["id"]):
        if row["quantity"] > 0:
            return row["location_code"], "already stocks this product"

    locations = db.list_location_capacity_info()
    category = product["category"]

    if category:
        same_category = [
            loc for loc in locations
            if category in loc["categories"] and loc["used_slots"] < loc["capacity"]
        ]
        if same_category:
            same_category.sort(key=lambda loc: loc["used_slots"])
            return same_category[0]["code"], f"already stocks {category}"

    open_locations = [loc for loc in locations if loc["used_slots"] < loc["capacity"]]
    if not open_locations:
        raise InventoryError(
            "No location has room for another product. Add a location or increase a capacity."
        )
    open_locations.sort(key=lambda loc: loc["used_slots"])
    return open_locations[0]["code"], "next available space"


def assign_inventory_auto(sku, quantity_change, reason):
    """Like assign_inventory, but picks the location automatically instead
    of requiring one. Returns (location_code, reason_text) for the flash message."""
    location_code, why = suggest_location_for_sku(sku)
    assign_inventory(sku, location_code, quantity_change, reason)
    return location_code, why


# ---------- lookup ----------

def lookup_by_sku(sku):
    product = db.get_product_by_sku(sku)
    if not product:
        raise InventoryError(f"No product with SKU '{sku}'.")
    return {
        "product": product,
        "inventory": db.list_inventory_by_product(product["id"]),
    }


def lookup_by_location(location_code):
    location = db.get_location_by_code(location_code)
    if not location:
        raise InventoryError(f"No location '{location_code}'.")
    return {
        "location": location,
        "inventory": db.list_inventory_by_location(location["id"]),
    }


# ---------- reconciliation ----------

def reconcile(sku, location_code, physical_count):
    """Compare a physical count against the system's expected quantity.
    The physical count always wins and becomes the new system quantity;
    a discrepancy is flagged (but not prevented) when the two disagree."""
    product = db.get_product_by_sku(sku)
    if not product:
        raise InventoryError(f"No product with SKU '{sku}'.")

    location = db.get_location_by_code(location_code)
    if not location:
        raise InventoryError(f"No location '{location_code}'.")

    if physical_count < 0:
        raise InventoryError("Physical count can't be negative.")

    current = db.get_inventory(product["id"], location["id"])
    expected_quantity = current["quantity"] if current else 0
    discrepancy = expected_quantity != physical_count

    db.upsert_inventory(product["id"], location["id"], physical_count)
    db.insert_movement(
        product["id"], location["id"],
        expected_quantity, physical_count,
        reason="counted", discrepancy=int(discrepancy),
    )

    return {
        "expected_quantity": expected_quantity,
        "physical_count": physical_count,
        "discrepancy": discrepancy,
        "difference": physical_count - expected_quantity,
    }


# ---------- movement history ----------

def movement_history_for_product(sku):
    product = db.get_product_by_sku(sku)
    if not product:
        raise InventoryError(f"No product with SKU '{sku}'.")
    return db.list_movements_by_product(product["id"])


def movement_history_for_location(location_code):
    location = db.get_location_by_code(location_code)
    if not location:
        raise InventoryError(f"No location '{location_code}'.")
    return db.list_movements_by_location(location["id"])
