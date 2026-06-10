import os
import json
import uuid
import io
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS

INGRESS_PATH = os.environ.get("INGRESS_PATH", "")
app = Flask(__name__)
CORS(app)

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


DEFAULT_STRUCTURES = {
    "list.json": {"items": []},
    "recipes.json": {"recipes": []},
    "history.json": {"shops": [], "total_saved": 0, "total_spent": 0},
    "aldi_list.json": {"active": False, "items": [], "created": None, "shop_option": None},
    "price_history.json": {},
    "settings.json": {},
}

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    default = DEFAULT_STRUCTURES.get(filename, {})
    try:
        with open(path) as f:
            data = json.load(f)
        # Guard: ensure expected top-level keys exist (handles empty/legacy files)
        if isinstance(data, dict) and isinstance(default, dict):
            for key, val in default.items():
                data.setdefault(key, val if not isinstance(val, (list, dict)) else type(val)())
        return data
    except Exception:
        # Return a fresh copy of the default structure
        return json.loads(json.dumps(default))

def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def r(path, **kwargs):
    """Register route with and without ingress prefix."""
    def decorator(f):
        app.add_url_rule(path, f.__name__ + "_p", f, **kwargs)
        if INGRESS_PATH:
            app.add_url_rule(INGRESS_PATH + path, f.__name__ + "_i", f, **kwargs)
        return f
    return decorator


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.route("/")
@app.route(INGRESS_PATH + "/" if INGRESS_PATH else "/x_never_match")
def index():
    return render_template("index.html", ingress_path=INGRESS_PATH)


# ── My List ────────────────────────────────────────────────────────────────────

@r("/api/list", methods=["GET"])
def get_list():
    return jsonify(load_json("list.json"))

@r("/api/list/item", methods=["POST"])
def add_item():
    data = load_json("list.json")
    item = request.json
    item["id"] = str(uuid.uuid4())
    item.setdefault("qty", 1)
    item.setdefault("unit", "")
    item.setdefault("details", "")
    item.setdefault("category", "")
    item.setdefault("notes", "")
    item.setdefault("included", True)
    item.setdefault("is_cupboard", False)
    item.setdefault("is_pantry", False)
    item.setdefault("sources", ["manual"])
    item.setdefault("recipe_tags", [])
    item.setdefault("purchase_count", 0)
    item.setdefault("last_purchased", None)
    data["items"].append(item)
    save_json("list.json", data)
    return jsonify(item)

@r("/api/list/item/<item_id>", methods=["PUT"])
def update_item(item_id):
    data = load_json("list.json")
    for i, item in enumerate(data["items"]):
        if item["id"] == item_id:
            updates = request.json
            original_name = item.get("item", "")
            # If the user manually edits qty on a recipe-linked item, store the
            # difference as manual_qty so the edit survives future recomputes.
            if "qty" in updates and item.get("recipe_quantities"):
                try:
                    contributions = sum(float(v) for v in item["recipe_quantities"].values())
                    updates["manual_qty"] = max(0, round(float(updates["qty"]) - contributions, 2))
                except (TypeError, ValueError):
                    pass
            data["items"][i] = {**item, **updates}
            # Two-way sync: if item or details changed, update linked recipe ingredients
            if "item" in updates or "details" in updates:
                _sync_item_to_recipes(data["items"][i], original_name)
            save_json("list.json", data)
            return jsonify(data["items"][i])
    return jsonify({"error": "Not found"}), 404

@r("/api/list/item/<item_id>", methods=["DELETE"])
def delete_item(item_id):
    data = load_json("list.json")
    data["items"] = [i for i in data["items"] if i["id"] != item_id]
    save_json("list.json", data)
    return jsonify({"success": True})

@r("/api/list/toggle/<item_id>", methods=["POST"])
def toggle_item(item_id):
    data = load_json("list.json")
    for item in data["items"]:
        if item["id"] == item_id:
            item["included"] = not item.get("included", True)
            save_json("list.json", data)
            return jsonify(item)
    return jsonify({"error": "Not found"}), 404

def _sync_item_to_recipes(list_item, original_name=""):
    """Sync list item name/details changes back to linked recipe ingredients."""
    recipe_tags = list_item.get("recipe_tags", [])
    if not recipe_tags:
        return
    recipes_data = load_json("recipes.json")
    changed = False
    new_name = list_item.get("item", "").lower()
    old_name = (original_name or "").lower()
    for recipe in recipes_data.get("recipes", []):
        if recipe["id"] not in recipe_tags:
            continue
        for ing in recipe.get("ingredients", []):
            ing_name = ing.get("item", "").lower()
            # Match by current name OR the pre-rename name
            if ing_name == new_name or (old_name and ing_name == old_name):
                if "item" in list_item:
                    ing["item"] = list_item["item"]
                if "details" in list_item:
                    ing["details"] = list_item["details"]
                changed = True
    if changed:
        save_json("recipes.json", recipes_data)


# ── Recipes ────────────────────────────────────────────────────────────────────

@r("/api/recipes", methods=["GET"])
def get_recipes():
    return jsonify(load_json("recipes.json"))

@r("/api/recipes", methods=["POST"])
def add_recipe():
    payload = request.json
    source_type = payload.get("source_type")

    recipe = {
        "id": str(uuid.uuid4()),
        "name": payload.get("name", "New Recipe"),
        "servings": payload.get("servings", 4),
        "base_servings": payload.get("servings", 4),
        "this_week_servings": payload.get("servings", 4),
        "ingredients": [],
        "notes": payload.get("notes", ""),
        "source_type": source_type,
        "source_url": payload.get("url", ""),
        "cook_count": 0,
        "last_cooked": None,
        "active_this_week": False,
        "created": datetime.now().isoformat()
    }

    if source_type == "url":
        from claude_helper import extract_recipe_from_url
        url = (payload.get("url") or "").strip()
        if not url:
            return jsonify({"error": "No URL provided"}), 400
        extracted = extract_recipe_from_url(url)
        if "error" in extracted:
            return jsonify({"error": extracted["error"]}), 500
        recipe.update({
            "name": extracted.get("name", recipe["name"]),
            "servings": extracted.get("servings", 4),
            "base_servings": extracted.get("servings", 4),
            "this_week_servings": extracted.get("servings", 4),
            "ingredients": extracted.get("ingredients", []),
            "notes": extracted.get("notes", ""),
        })

    elif source_type == "image":
        import base64
        from claude_helper import extract_recipe_from_image
        image_data = payload.get("image_data")
        if not image_data:
            return jsonify({"error": "No image provided"}), 400
        media_type = payload.get("media_type", "image/jpeg")
        extracted = extract_recipe_from_image(image_data, media_type)
        if "error" in extracted:
            return jsonify({"error": extracted["error"]}), 500
        recipe.update({
            "name": extracted.get("name", recipe["name"]),
            "servings": extracted.get("servings", 4),
            "base_servings": extracted.get("servings", 4),
            "this_week_servings": extracted.get("servings", 4),
            "ingredients": extracted.get("ingredients", []),
            "notes": extracted.get("notes", ""),
        })
        img_path = os.path.join(UPLOAD_FOLDER, f"{recipe['id']}.jpg")
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(image_data))

    elif source_type == "manual":
        recipe.update({
            "name": payload.get("name", "New Recipe"),
            "servings": int(payload.get("servings", 4)),
            "base_servings": int(payload.get("servings", 4)),
            "this_week_servings": int(payload.get("servings", 4)),
            "ingredients": payload.get("ingredients", []),
            "notes": payload.get("notes", ""),
        })

    for ing in recipe["ingredients"]:
        ing.setdefault("id", str(uuid.uuid4()))

    data = load_json("recipes.json")
    data["recipes"].append(recipe)
    save_json("recipes.json", data)
    return jsonify(recipe)

@r("/api/recipes/<recipe_id>", methods=["PUT"])
def update_recipe(recipe_id):
    data = load_json("recipes.json")
    for i, rec in enumerate(data["recipes"]):
        if rec["id"] == recipe_id:
            updates = request.json
            data["recipes"][i] = {**rec, **updates}
            # Two-way sync: if ingredient changed, update linked list items
            if "ingredients" in updates:
                _sync_recipe_to_list(recipe_id, updates["ingredients"])
            save_json("recipes.json", data)
            return jsonify(data["recipes"][i])
    return jsonify({"error": "Not found"}), 404

def _sync_recipe_to_list(recipe_id, ingredients):
    """Sync recipe ingredient changes to linked list items."""
    list_data = load_json("list.json")
    changed = False
    for item in list_data["items"]:
        if recipe_id not in item.get("recipe_tags", []):
            continue
        for ing in ingredients:
            if ing.get("item", "").lower() == item.get("item", "").lower():
                if item.get("details") != ing.get("details"):
                    item["details"] = ing.get("details", "")
                    changed = True
    if changed:
        save_json("list.json", list_data)

@r("/api/recipes/<recipe_id>", methods=["DELETE"])
def delete_recipe(recipe_id):
    data = load_json("recipes.json")
    list_data = load_json("list.json")
    for item in list_data["items"]:
        if recipe_id in item.get("recipe_tags", []):
            item["recipe_tags"].remove(recipe_id)
            # Remove this recipe's quantity contribution and recompute
            if "recipe_quantities" in item:
                item["recipe_quantities"].pop(recipe_id, None)
            remaining = item.get("recipe_tags", [])
            has_manual = "manual" in item.get("sources", []) or (item.get("manual_qty") or 0) > 0
            if remaining or has_manual:
                item["qty"] = _recompute_qty(item)
            else:
                item["included"] = False
    save_json("list.json", list_data)
    data["recipes"] = [rec for rec in data["recipes"] if rec["id"] != recipe_id]
    save_json("recipes.json", data)
    return jsonify({"success": True})

@r("/api/recipes/<recipe_id>/toggle", methods=["POST"])
def toggle_recipe(recipe_id):
    from claude_helper import units_compatible
    recipes_data = load_json("recipes.json")
    list_data = load_json("list.json")
    recipe = next((rec for rec in recipes_data["recipes"] if rec["id"] == recipe_id), None)
    if not recipe:
        return jsonify({"error": "Not found"}), 404

    active = not recipe.get("active_this_week", False)
    recipe["active_this_week"] = active
    ratio = recipe.get("this_week_servings", recipe["base_servings"]) / max(recipe["base_servings"], 1)

    if active:
        for ing in recipe["ingredients"]:
            if ing.get("is_pantry") or ing.get("is_small_qty"):
                continue
            scaled = round(float(ing.get("qty", 1)) * ratio, 2)
            ing_unit = (ing.get("unit") or "").lower().strip()

            # Find an existing list item with the same name AND compatible unit
            existing = next((item for item in list_data["items"]
                             if item["item"].lower() == ing["item"].lower()
                             and (item.get("unit") or "").lower().strip() == ing_unit), None)

            if existing:
                # FIRST recipe contribution to a pre-existing manual item:
                # capture its current qty as the manual base so it isn't wiped.
                if not existing.get("recipe_quantities") and "manual" in existing.get("sources", []) \
                        and not existing.get("manual_qty"):
                    existing["manual_qty"] = float(existing.get("qty", 0) or 0)
                # Record this recipe's contribution, then recompute qty as sum of all contributions
                existing.setdefault("recipe_quantities", {})
                existing["recipe_quantities"][recipe_id] = scaled
                if recipe_id not in existing.get("recipe_tags", []):
                    existing.setdefault("recipe_tags", []).append(recipe_id)
                existing["qty"] = _recompute_qty(existing)
                existing["included"] = True
            else:
                list_data["items"].append({
                    "id": str(uuid.uuid4()),
                    "item": ing["item"],
                    "qty": scaled,
                    "unit": ing_unit,
                    "details": ing.get("details", ""),
                    "category": ing.get("category", ""),
                    "notes": "",
                    "included": True,
                    "is_cupboard": False,
                    "is_pantry": False,
                    "sources": ["recipe"],
                    "recipe_tags": [recipe_id],
                    "recipe_quantities": {recipe_id: scaled},
                    "manual_qty": 0,
                    "purchase_count": 0,
                    "last_purchased": None
                })
    else:
        # Toggle OFF — remove this recipe's contribution
        for item in list_data["items"]:
            if recipe_id not in item.get("recipe_tags", []):
                continue
            item["recipe_tags"].remove(recipe_id)
            if "recipe_quantities" in item:
                item["recipe_quantities"].pop(recipe_id, None)
            remaining_recipes = item.get("recipe_tags", [])
            has_manual = "manual" in item.get("sources", []) or (item.get("manual_qty") or 0) > 0
            if remaining_recipes or has_manual:
                # Still needed by another recipe or manually — keep ticked, reduce qty
                item["qty"] = _recompute_qty(item)
                item["included"] = True
            else:
                # Only this recipe needed it — untick, keep in list
                item["included"] = False

    for i, rec in enumerate(recipes_data["recipes"]):
        if rec["id"] == recipe_id:
            recipes_data["recipes"][i] = recipe

    save_json("recipes.json", recipes_data)
    save_json("list.json", list_data)
    return jsonify({"recipe": recipe, "active": active})


def _recompute_qty(item):
    """Total qty = sum of all active recipe contributions + any manual base qty."""
    contributions = sum(float(v) for v in (item.get("recipe_quantities") or {}).values())
    manual = float(item.get("manual_qty", 0) or 0)
    total = round(contributions + manual, 2)
    return total if total > 0 else round(float(item.get("qty", 1)), 2)

@r("/api/recipes/<recipe_id>/servings", methods=["POST"])
def update_servings(recipe_id):
    recipes_data = load_json("recipes.json")
    list_data = load_json("list.json")
    new_servings = max(1, int(request.json.get("servings", 4)))
    recipe = next((rec for rec in recipes_data["recipes"] if rec["id"] == recipe_id), None)
    if not recipe:
        return jsonify({"error": "Not found"}), 404

    new_ratio = new_servings / max(recipe["base_servings"], 1)
    recipe["this_week_servings"] = new_servings

    if recipe.get("active_this_week"):
        for item in list_data["items"]:
            if recipe_id not in item.get("recipe_tags", []):
                continue
            ing = next((i for i in recipe["ingredients"]
                        if i["item"].lower() == item["item"].lower()
                        and (i.get("unit") or "").lower().strip() == (item.get("unit") or "").lower().strip()), None)
            if ing:
                new_c = round(float(ing.get("qty", 1)) * new_ratio, 2)
                item.setdefault("recipe_quantities", {})[recipe_id] = new_c
                item["qty"] = _recompute_qty(item)

    for i, rec in enumerate(recipes_data["recipes"]):
        if rec["id"] == recipe_id:
            recipes_data["recipes"][i] = recipe

    save_json("recipes.json", recipes_data)
    save_json("list.json", list_data)
    return jsonify({"success": True, "servings": new_servings})

@r("/api/recipes/<recipe_id>/image", methods=["GET"])
def get_recipe_image(recipe_id):
    img_path = os.path.join(UPLOAD_FOLDER, f"{recipe_id}.jpg")
    if os.path.exists(img_path):
        return send_file(img_path, mimetype="image/jpeg")
    return jsonify({"error": "No image"}), 404


# ── Settings ───────────────────────────────────────────────────────────────────

@r("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_json("settings.json"))

@r("/api/settings", methods=["PUT"])
def update_settings():
    data = load_json("settings.json")
    data.update(request.json)
    save_json("settings.json", data)
    return jsonify(data)

@r("/api/settings/categories", methods=["POST"])
def add_category():
    data = load_json("settings.json")
    cat = request.json.get("category", "").strip()
    if cat and cat not in data.get("categories", []):
        data.setdefault("categories", []).append(cat)
        save_json("settings.json", data)
    return jsonify(data.get("categories", []))

@r("/api/settings/categories/<cat>", methods=["DELETE"])
def delete_category(cat):
    data = load_json("settings.json")
    data["categories"] = [c for c in data.get("categories", []) if c != cat]
    save_json("settings.json", data)
    return jsonify(data.get("categories", []))

@r("/api/stores/woolworths", methods=["GET"])
def search_woolworths_stores():
    from scraper import search_woolworths_stores as _search
    q = request.args.get("q", "")
    if not q:
        return jsonify([])
    return jsonify(_search(q))

@r("/api/stores/coles", methods=["GET"])
def search_coles_stores():
    from scraper import search_coles_stores as _search
    q = request.args.get("q", "")
    if not q:
        return jsonify([])
    return jsonify(_search(q))


# ── Analytics ──────────────────────────────────────────────────────────────────

@r("/api/analytics", methods=["GET"])
def get_analytics():
    return jsonify(load_json("history.json"))

@r("/api/analytics/shop/<shop_id>", methods=["PUT"])
def update_shop(shop_id):
    history = load_json("history.json")
    for i, shop in enumerate(history.get("shops", [])):
        if shop["id"] == shop_id:
            history["shops"][i] = {**shop, **request.json}
            save_json("history.json", history)
            return jsonify(history["shops"][i])
    return jsonify({"error": "Not found"}), 404

@r("/api/analytics/shop/<shop_id>", methods=["DELETE"])
def delete_shop(shop_id):
    history = load_json("history.json")
    history["shops"] = [s for s in history.get("shops", []) if s["id"] != shop_id]
    # Recalculate totals
    history["total_spent"] = sum(s.get("total", 0) for s in history["shops"])
    history["total_saved"] = sum(s.get("saved", 0) + s.get("rewards_plus_saved", 0) for s in history["shops"])
    save_json("history.json", history)
    return jsonify({"success": True})

@r("/api/analytics/clear", methods=["POST"])
def clear_analytics():
    data = {"shops": [], "total_saved": 0, "total_spent": 0}
    save_json("history.json", data)
    return jsonify(data)


# ── Aldi List ──────────────────────────────────────────────────────────────────

@r("/api/aldi-list", methods=["GET"])
def get_aldi_list():
    return jsonify(load_json("aldi_list.json"))

@r("/api/aldi-list", methods=["POST"])
def set_aldi_list():
    data = request.json
    data["created"] = datetime.now().isoformat()
    data["active"] = True
    save_json("aldi_list.json", data)
    return jsonify(data)

@r("/api/aldi-list/toggle/<item_id>", methods=["POST"])
def toggle_aldi_item(item_id):
    data = load_json("aldi_list.json")
    for item in data.get("items", []):
        if item["id"] == item_id:
            item["checked"] = not item.get("checked", False)
            break
    save_json("aldi_list.json", data)
    return jsonify(data)

@r("/api/aldi-list/clear", methods=["POST"])
def clear_aldi_list():
    data = {"active": False, "items": [], "created": None, "shop_option": None}
    save_json("aldi_list.json", data)
    return jsonify(data)


# ── Shop ───────────────────────────────────────────────────────────────────────

@r("/api/shop/prepare", methods=["POST"])
def prepare_shop():
    from compare import consolidate_items
    list_data = load_json("list.json")
    active_items = [i for i in list_data["items"] if i.get("included", True)]
    consolidated = consolidate_items(active_items)
    # No pantry step: every included list item is bought. Clarification happens
    # AFTER the price search, grounded in real product candidates.
    return jsonify({
        "items": consolidated,
        "item_count": len(consolidated)
    })

@r("/api/shop/prices", methods=["POST"])
def get_prices():
    from scraper import search_all_stores, get_delivery_fees
    from compare import calculate_options
    payload = request.json
    items = payload.get("items", [])
    settings = load_json("settings.json")
    priced_items = []
    not_found = []
    manual_needed = []
    clarifications = []

    for item in items:
        prices = search_all_stores(item, settings)
        priced_item = {**item,
                       "woolworths": prices.get("woolworths"),
                       "coles": prices.get("coles"),
                       "aldi": prices.get("aldi")}
        priced_items.append(priced_item)

        found_any = any([prices.get("woolworths"), prices.get("coles"), prices.get("aldi")])
        if not found_any:
            not_found.append(item["item"])
            manual_needed.append({"id": item.get("id"), "item": item["item"]})
            continue

        # Ambiguity detection: only surface a clarification when the matched
        # products are GENUINELY different (not just pack-size/brand variants).
        all_alts = []
        for store in ["woolworths", "coles", "aldi"]:
            sd = prices.get(store)
            if sd and sd.get("alternatives"):
                for alt in sd["alternatives"]:
                    all_alts.append({**alt, "store": store})

        # De-dup by product name
        distinct = {}
        for a in all_alts:
            if a["name"] not in distinct:
                distinct[a["name"]] = a

        if len(distinct) > 1:
            from claude_helper import assess_ambiguity
            if assess_ambiguity(item.get("item", ""), item.get("details", ""), list(distinct.values())):
                clarifications.append({
                    "item_id": item.get("id"),
                    "item_name": item.get("item"),
                    "options": sorted(distinct.values(), key=lambda x: x["total"])[:6]
                })

    delivery_fees = get_delivery_fees(settings)
    options = calculate_options(priced_items, delivery_fees, settings)
    return jsonify({
        "options": options,
        "priced_items": priced_items,
        "not_found": not_found,
        "manual_needed": manual_needed,
        "clarifications": clarifications
    })

@r("/api/shop/select-product", methods=["POST"])
def select_product():
    """Lock in a user-chosen product for an ambiguous item, recompute that item's pricing."""
    from scraper import calc_packs_needed
    payload = request.json
    chosen = payload.get("chosen", {})        # {name, unit_price, store, ...}
    item = payload.get("item", {})            # the priced item to update
    store = chosen.get("store")
    if not store:
        return jsonify({"error": "No store specified"}), 400
    pack = calc_packs_needed(item.get("qty", 1), item.get("unit", ""), chosen.get("name", ""))
    unit_price = float(chosen.get("unit_price", 0))
    updated = {
        "name": chosen.get("name", ""),
        "price": unit_price,
        "unit_price": unit_price,
        "packs": pack["packs"],
        "pack_label": pack["pack_label"],
        "pack_note": pack["note"],
        "line_total": round(unit_price * pack["packs"], 2),
        "url": chosen.get("url", ""),
        "on_special": chosen.get("on_special", False),
        "store": store,
        "user_selected": True
    }
    return jsonify({"store": store, "data": updated})

@r("/api/shop/prices/recompute", methods=["POST"])
def recompute_prices():
    """Recompute options after user has confirmed product choices for ambiguous items."""
    from scraper import get_delivery_fees
    from compare import calculate_options
    payload = request.json
    priced_items = payload.get("priced_items", [])
    settings = load_json("settings.json")
    delivery_fees = get_delivery_fees(settings)
    options = calculate_options(priced_items, delivery_fees, settings)
    return jsonify({"options": options, "priced_items": priced_items})

@r("/api/shop/prices/manual", methods=["POST"])
def set_manual_price():
    """Set manual price for an item that couldn't be found."""
    payload = request.json
    item_name = payload.get("item")
    store = payload.get("store")
    price = float(payload.get("price", 0))
    if item_name and store and price > 0:
        from scraper import record_price
        record_price(item_name, store, price, item_name)
    return jsonify({"success": True})

@r("/api/shop/specials", methods=["POST"])
def get_specials():
    from scraper import check_for_specials
    from claude_helper import suggest_bulk_buys
    items = request.json.get("items", [])
    settings = load_json("settings.json")
    specials = check_for_specials(items, settings)
    suggestions = suggest_bulk_buys(specials, settings)
    return jsonify({"specials": specials, "suggestions": suggestions})

@r("/api/shop/prepare-cart", methods=["POST"])
def prepare_cart():
    from scraper import build_woolworths_cart_url, build_coles_cart_url, format_store_list
    payload = request.json
    option = payload.get("option", {})
    split = option.get("split", {})
    result = {}
    if "woolworths" in split and split["woolworths"]:
        items = split["woolworths"]
        result["woolworths"] = {
            "deep_link": build_woolworths_cart_url(items),
            "list": format_store_list(items, "woolworths"),
            "item_count": len(items)
        }
    if "coles" in split and split["coles"]:
        items = split["coles"]
        result["coles"] = {
            "deep_link": build_coles_cart_url(items),
            "list": format_store_list(items, "coles"),
            "item_count": len(items)
        }
    if "aldi" in split and split["aldi"]:
        items = split["aldi"]
        aldi_items = []
        for i in items:
            ad = i.get("aldi") or {}
            aldi_items.append({
                "id": str(uuid.uuid4()),
                "item": i.get("item", ""),
                "matched_name": ad.get("name", ""),
                "buy_qty": ad.get("pack_note") or (f"{ad.get('packs', 1)} × {ad.get('pack_label', '')}" if ad.get("pack_label") else str(ad.get("packs", 1))),
                "packs": ad.get("packs", 1),
                "pack_label": ad.get("pack_label", ""),
                "qty": i.get("qty", 1),
                "unit": i.get("unit", ""),
                "details": i.get("details", ""),
                "category": i.get("category", ""),
                "unit_price": ad.get("unit_price", ad.get("price")),
                "price": ad.get("line_total", ad.get("price")),
                "on_special": ad.get("on_special", False),
                "checked": False
            })
        save_json("aldi_list.json", {
            "active": True,
            "items": aldi_items,
            "created": datetime.now().isoformat(),
            "shop_option": option.get("label", "")
        })
        result["aldi"] = {"items": aldi_items, "item_count": len(aldi_items)}
    return jsonify(result)

@r("/api/shop/complete", methods=["POST"])
def complete_shop():
    payload = request.json
    option = payload.get("option", {})
    settings = load_json("settings.json")
    history = load_json("history.json")
    today = datetime.now().isoformat()
    option_total = float(option.get("total", 0) or 0)
    raw_cheapest = payload.get("cheapest_single_store")
    try:
        cheapest_single = float(raw_cheapest)
        if not (cheapest_single == cheapest_single and abs(cheapest_single) != float("inf")):  # NaN/Inf guard
            cheapest_single = option_total
    except (TypeError, ValueError):
        cheapest_single = option_total
    saved = round(max(cheapest_single - option_total, 0), 2)
    rewards_saved = round(option.get("subtotal", 0) * 0.1, 2) if option.get("rewards_plus_applied") else 0
    shop_record = {
        "id": str(uuid.uuid4()), "date": today,
        "stores": option.get("stores", []),
        "total": option.get("total", 0),
        "subtotal": option.get("subtotal", 0),
        "delivery": option.get("delivery", 0),
        "rewards_plus_applied": option.get("rewards_plus_applied", False),
        "rewards_plus_saved": rewards_saved,
        "item_count": payload.get("item_count", 0),
        "saved": saved
    }
    history["shops"].append(shop_record)
    history["total_spent"] = round(history.get("total_spent", 0) + shop_record["total"], 2)
    history["total_saved"] = round(history.get("total_saved", 0) + saved + rewards_saved, 2)
    save_json("history.json", history)

    list_data = load_json("list.json")
    purchased_ids = {i["id"] for i in payload.get("items", [])}
    for item in list_data["items"]:
        if item["id"] in purchased_ids:
            item["purchase_count"] = item.get("purchase_count", 0) + 1
            item["last_purchased"] = today
    save_json("list.json", list_data)

    if option.get("rewards_plus_applied"):
        settings["rewards_plus_last_used"] = today
        settings["rewards_plus_active"] = False
        settings["rewards_plus_code"] = ""
        save_json("settings.json", settings)

    # Recipes stay active — no auto-reset
    return jsonify({"success": True, "shop": shop_record})


# ── Exports ────────────────────────────────────────────────────────────────────

@r("/api/export/excel", methods=["POST"])
def export_excel():
    from exports import export_excel as _export
    list_data = load_json("list.json")
    recipes_data = load_json("recipes.json")
    history_data = load_json("history.json")
    store_lists = (request.get_json(silent=True) or {}).get("store_lists")
    xlsx_bytes = _export(list_data, recipes_data, history_data, store_lists)
    return Response(
        xlsx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=smart-cart-{datetime.now().strftime('%Y%m%d')}.xlsx"}
    )

@r("/api/export/pdf", methods=["GET"])
def export_pdf():
    from exports import export_pdf as _export
    list_data = load_json("list.json")
    settings = load_json("settings.json")
    pdf_bytes = _export(list_data, settings)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=smart-cart-{datetime.now().strftime('%Y%m%d')}.pdf"}
    )

@r("/api/export/text", methods=["POST"])
def export_text():
    from exports import export_plain_text as _export
    list_data = load_json("list.json")
    payload = request.json or {}
    store_lists = payload.get("store_lists")
    mode = payload.get("mode", "list")
    text = _export(list_data, store_lists, mode)
    return jsonify({"text": text})

@r("/api/price-history", methods=["GET"])
def get_price_history():
    from scraper import load_price_history
    return jsonify(load_price_history())


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n🛒 Smart Cart v1.4.1 running on port {port}")
    print(f"   Ingress path: '{INGRESS_PATH}'")
    app.run(host="0.0.0.0", port=port, debug=False)
