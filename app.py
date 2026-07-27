# Web/UI layer: Flask routes only. Each route reads form/query input, calls
# into inventory.py to do the real work, and renders a template with the
# result. No SQL and no business rules should ever appear in this file.

from flask import Flask, render_template, request, redirect, url_for, flash

import barcode_labels
import db
import inventory
from inventory import InventoryError

app = Flask(__name__)
app.secret_key = "dev-only-secret-key"  # fine for local MVP use, not for production
app.jinja_env.globals["barcode_svg"] = barcode_labels.svg_for


@app.route("/")
def home():
    summary = {
        "total_products": db.count_products(),
        "total_locations": db.count_locations(),
        "total_discrepancies": db.count_discrepancies(),
        "total_movements": db.count_movements(),
        "recent_movements": db.list_recent_movements(8),
    }
    return render_template("home.html", summary=summary)


# ---------- products ----------

@app.route("/products", methods=["GET", "POST"])
def products():
    if request.method == "POST":
        try:
            sku = inventory.add_product(
                sku=request.form["sku"].strip() or None,
                name=request.form["name"].strip(),
                category=request.form["category"].strip() or None,
            )
            flash(f"Added product {sku}.", "success")
        except InventoryError as e:
            flash(str(e), "error")
        return redirect(url_for("products"))

    suggested_sku = inventory.generate_unique_sku() if request.args.get("suggest") else None
    return render_template("products.html", products=db.list_products(), suggested_sku=suggested_sku)


@app.route("/products/<sku>/delete", methods=["POST"])
def delete_product(sku):
    try:
        inventory.delete_product(sku)
        flash(f"Deleted product {sku}.", "success")
    except InventoryError as e:
        flash(str(e), "error")
    return redirect(url_for("products"))


# ---------- locations ----------

@app.route("/locations", methods=["GET", "POST"])
def locations():
    if request.method == "POST":
        try:
            code = inventory.add_location(
                aisle=request.form["aisle"].strip(),
                shelf=request.form["shelf"].strip(),
                bin_=request.form["bin"].strip(),
                capacity=int(request.form.get("capacity") or 5),
            )
            flash(f"Added location {code}.", "success")
        except ValueError:
            flash("Capacity must be a whole number.", "error")
        except InventoryError as e:
            flash(str(e), "error")
        return redirect(url_for("locations"))

    return render_template("locations.html", locations=db.list_location_capacity_info())


@app.route("/locations/<code>/delete", methods=["POST"])
def delete_location(code):
    try:
        inventory.delete_location(code)
        flash(f"Deleted location {code}.", "success")
    except InventoryError as e:
        flash(str(e), "error")
    return redirect(url_for("locations"))


# ---------- assign inventory ----------

@app.route("/assign", methods=["GET", "POST"])
def assign():
    if request.method == "POST":
        try:
            quantity_change = int(request.form["quantity_change"])
            sku = request.form["sku"].strip()
            reason = request.form["reason"]

            if request.form.get("auto_place"):
                location_code, why = inventory.assign_inventory_auto(sku, quantity_change, reason)
                flash(f"Placed in {location_code} ({why}).", "success")
            else:
                inventory.assign_inventory(
                    sku=sku,
                    location_code=request.form.get("location_code", "").strip(),
                    quantity_change=quantity_change,
                    reason=reason,
                )
                flash("Inventory updated.", "success")
        except (InventoryError, ValueError) as e:
            flash(str(e) if isinstance(e, InventoryError) else "Quantity change must be a whole number.", "error")
        return redirect(url_for("assign"))

    return render_template(
        "assign.html",
        products=db.list_products(),
        locations=db.list_locations(),
        reasons=sorted(inventory.VALID_ASSIGN_REASONS),
    )


# ---------- lookup ----------

@app.route("/lookup")
def lookup():
    sku = request.args.get("sku", "").strip()
    location_code = request.args.get("location_code", "").strip()
    result = None

    try:
        if sku:
            result = ("sku", inventory.lookup_by_sku(sku))
        elif location_code:
            result = ("location", inventory.lookup_by_location(location_code))
    except InventoryError as e:
        flash(str(e), "error")

    return render_template(
        "lookup.html",
        products=db.list_products(),
        locations=db.list_locations(),
        result=result,
    )


# ---------- reconcile ----------

@app.route("/reconcile", methods=["GET", "POST"])
def reconcile():
    result = None
    if request.method == "POST":
        sku = request.form["sku"].strip()
        location_code = request.form["location_code"].strip()
        try:
            physical_count = int(request.form["physical_count"])
            result = inventory.reconcile(sku, location_code, physical_count)
            result["sku"] = sku
            result["location_code"] = location_code
        except ValueError:
            flash("Physical count must be a whole number.", "error")
        except InventoryError as e:
            flash(str(e), "error")

    return render_template(
        "reconcile.html",
        products=db.list_products(),
        locations=db.list_locations(),
        result=result,
    )


# ---------- movement history ----------

@app.route("/movements")
def movements():
    sku = request.args.get("sku", "").strip()
    location_code = request.args.get("location_code", "").strip()
    history = None

    try:
        if sku:
            history = ("sku", sku, inventory.movement_history_for_product(sku))
        elif location_code:
            history = ("location", location_code, inventory.movement_history_for_location(location_code))
    except InventoryError as e:
        flash(str(e), "error")

    return render_template(
        "movements.html",
        products=db.list_products(),
        locations=db.list_locations(),
        history=history,
    )


if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, port=5050)
