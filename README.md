# Warehouse Inventory Manager

A small web app for tracking what's actually in stock, where, in a warehouse
that uses aisle/shelf/bin locations. It solves the "system says X but the
shelf has Y" problem: every quantity change is logged, and a reconcile flow
lets you enter a physical count and see the discrepancy against what the
system expects.

## Features

- **Products & Locations** — add SKUs and aisle-shelf-bin locations, each
  with an auto-generated printable/scannable barcode.
- **Assign Inventory** — scan a product, scan (or auto-place into) a
  location, enter a quantity, and it's logged.
- **Auto-placement** — leave the location blank and the system finds an
  open spot, preferring a location that already stocks the same category.
- **Lookup** — search by SKU or by location to see current stock.
- **Reconcile** — enter a physical count for a product+location; the system
  flags a discrepancy if it doesn't match what it expected.
- **Movement history** — a permanent, append-only log of every change:
  what, when, old quantity, new quantity, and why.

## Requirements

- Python 3.9+

## Setup

```bash
cd warehouse
pip3 install -r requirements.txt
python3 app.py
```

Then open **http://127.0.0.1:5050** in your browser.

The first run creates a `warehouse.db` SQLite file in this folder — that's
where all your data lives. It's gitignored, so it stays local to your
machine and won't get committed.

## Project layout

- `schema.sql` — the database schema.
- `db.py` — data layer: all SQL lives here.
- `inventory.py` — business logic: validation rules (no negative stock,
  no deleting a product/location with history, auto-placement, etc).
- `barcode_labels.py` — renders SKUs/location codes as scannable barcodes.
- `app.py` — Flask routes; connects the web UI to the business logic.
- `templates/`, `static/` — the web UI.
