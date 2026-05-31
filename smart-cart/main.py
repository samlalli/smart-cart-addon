import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ─── Data helpers ─────────────────────────────────────────────────────────────

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ─── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── My List ──────────────────────────────────────────────────────────────────

@app.route("/api/list", methods=["GET"])
def get_list():
    return jsonify(load_json("list.json"))

@app.route("/api/list/item", methods=["POST"])
def add_item():
    data = load_json("list.json")
    item = request.json
    item["id"] = str(uuid.uuid4())
    item.setdefault("qty", 1)
    item.setdefault("unit", "")
    item.setdefault("details", "")
    item.setdefault("category", "")
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

@app.route("/api/list/item/<item_id>", methods=["PUT"])
def update_item(item_id):
    data = load_json("list.json")
    for i, item in enumerate(data["items"]):
        if item["id"] == item_id:
            data["items"][i] = {**item, **request.json}
            save_json("list.json", data)
            return jsonify(data["items"][i])
    return jsonify({"error": "Not found"}), 404

@app.route("/api/list/item/<item_id>", methods=["DELETE"])
def delete_item(item_id):
    data = load_json("list.json")
    data["items"] = [i for i in data["items"] if i["id"] != item_id]
    save_json("list.json", data)
    return jsonify({"success": True})

@app.route("/api/list/toggle/<item_id>", methods=["POST"])
def toggle_item(item_id):
    data = load_json("list.json")
    for item in data["items"]:
        if item["id"] == item_id:
            item["included"] = not item.get("included", True)
            save_json("list.json", data)
            return jsonify(item)
    return jsonify({"error": "Not found"}), 404


# ─── Recipes ──────────────────────────────────────────────────────────────────

@app.route("/api/recipes", methods=["GET"])
def get_recipes():
    return jsonify(load_json("recipes.json"))

@app.route("/api/recipes", methods=["POST"])
def add_recipe():
    from claude_helper import extract_recipe_from_url, extract_recipe_from_image
    payload = request.json
    source_type = payload.get("source_type")

    recipe = {
        "id": str(uuid.uuid4()),
        "name": payload.get("name", "New Recipe"),
        "servings": payload.get("servings", 4),
        "base_servings": payload.get("servings", 4),
        "this_week_servings": payload.get("servings", 4),
        "ingredients": [],
        "notes": "",
        "source_type": source_type,
        "source_url": payload.get("url", ""),
        "source_image": None,  # Stored separately to avoid huge JSON
        "cook_count": 0,
        "last_cooked": None,
        "active_this_week": False,
        "created": datetime.now().isoformat()
    }

    if source_type == "url":
        from claude_helper import extract_recipe_from_url
        extracted = extract_recipe_from_url(payload["url"])
        if "error" not in extracted:
            recipe.update({
                "name": extracted.get("name", recipe["name"]),
                "servings": extracted.get("servings", 4),
                "base_servings": extracted.get("servings", 4),
                "this_week_servings": extracted.get("servings", 4),
                "ingredients": extracted.get("ingredients", []),
                "notes": extracted.get("notes", ""),
            })
        else:
            return jsonify({"error": extracted["error"]}), 500

    elif source_type == "image":
        from claude_helper import extract_recipe_from_image
        image_data = payload.get("image_data")
        media_type = payload.get("media_type", "image/jpeg")
        # Save image thumbnail reference
        recipe["source_image"] = f"data:{media_type};base64,{image_data[:100]}..."  # Preview only
        extracted = extract_recipe_from_image(image_data, media_type)
        if "error" not in extracted:
            recipe.update({
                "name": extracted.get("name", recipe["name"]),
                "servings": extracted.get("servings", 4),
                "base_servings": extracted.get("servings", 4),
                "this_week_servings": extracted.get("servings", 4),
                "ingredients": extracted.get("ingredients", []),
                "notes": extracted.get("notes", ""),
            })
            # Save full image to disk
            import base64
            img_path = os.path.join(UPLOAD_FOLDER, f"{recipe['id']}.jpg")
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(image_data))
            recipe["source_image_path"] = img_path
        else:
            return jsonify({"error": extracted["error"]}), 500

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

@app.route("/api/recipes/<recipe_id>", methods=["PUT"])
def update_recipe(recipe_id):
    data = load_json("recipes.json")
    for i, r in enumerate(data["recipes"]):
        if r["id"] == recipe_id:
            data["recipes"][i] = {**r, **request.json}
            save_json("recipes.json", data)
            return jsonify(data["recipes"][i])
    return jsonify({"error": "Not found"}), 404

@app.route("/api/recipes/<recipe_id>", methods=["DELETE"])
def delete_recipe(recipe_id):
    data = load_json("recipes.json")
    list_data = load_json("list.json")
    # Remove recipe-only items from list
    list_data["items"] = [
        item for item in list_data["items"]
        if not (recipe_id in item.get("recipe_tags", []) and len(item.get("recipe_tags", [])) == 1 and item.get("sources") == ["recipe"])
    ]
    for item in list_data["items"]:
        if recipe_id in item.get("recipe_tags", []):
            item["recipe_tags"].remove(recipe_id)
    save_json("list.json", list_data)
    data["recipes"] = [r for r in data["recipes"] if r["id"] != recipe_id]
    save_json("recipes.json", data)
    return jsonify({"success": True})

@app.route("/api/recipes/<recipe_id>/toggle", methods=["POST"])
def toggle_recipe(recipe_id):
    recipes_data = load_json("recipes.json")
    list_data = load_json("list.json")
    recipe = next((r for r in recipes_data["recipes"] if r["id"] == recipe_id), None)
    if not recipe:
        return jsonify({"error": "Not found"}), 404

    active = not recipe.get("active_this_week", False)
    recipe["active_this_week"] = active

    if active:
        servings_ratio = recipe.get("this_week_servings", recipe["base_servings"]) / max(recipe["base_servings"], 1)
        for ing in recipe["ingredients"]:
            if ing.get("is_pantry"):
                continue
            scaled_qty = round(float(ing.get("qty", 1)) * servings_ratio, 2)
            existing = next((item for item in list_data["items"] if item["item"].lower() == ing["item"].lower()), None)
            if existing:
                if recipe_id not in existing.get("recipe_tags", []):
                    existing.setdefault("recipe_tags", []).append(recipe_id)
                existing["qty"] = round(float(existing.get("qty", 1)) + scaled_qty, 2)
                existing["included"] = True
            else:
                list_data["items"].append({
                    "id": str(uuid.uuid4()),
                    "item": ing["item"],
                    "qty": scaled_qty,
                    "unit": ing.get("unit", ""),
                    "details": ing.get("details", ""),
                    "category": "",
                    "included": True,
                    "is_cupboard": False,
                    "is_pantry": False,
                    "sources": ["recipe"],
                    "recipe_tags": [recipe_id],
                    "purchase_count": 0,
                    "last_purchased": None
                })
    else:
        items_to_remove = []
        for item in list_data["items"]:
            tags = item.get("recipe_tags", [])
            if recipe_id in tags:
                tags.remove(recipe_id)
                item["recipe_tags"] = tags
                if not tags and item.get("sources") == ["recipe"]:
                    items_to_remove.append(item["id"])
        list_data["items"] = [i for i in list_data["items"] if i["id"] not in items_to_remove]

    for i, r in enumerate(recipes_data["recipes"]):
        if r["id"] == recipe_id:
            recipes_data["recipes"][i] = recipe

    save_json("recipes.json", recipes_data)
    save_json("list.json", list_data)
    return jsonify({"recipe": recipe, "active": active})

@app.route("/api/recipes/<recipe_id>/servings", methods=["POST"])
def update_servings(recipe_id):
    recipes_data = load_json("recipes.json")
    list_data = load_json("list.json")
    new_servings = max(1, int(request.json.get("servings", 4)))
    recipe = next((r for r in recipes_data["recipes"] if r["id"] == recipe_id), None)
    if not recipe:
        return jsonify({"error": "Not found"}), 404

    old_ratio = recipe.get("this_week_servings", recipe["base_servings"]) / max(recipe["base_servings"], 1)
    new_ratio = new_servings / max(recipe["base_servings"], 1)
    recipe["this_week_servings"] = new_servings

    if recipe.get("active_this_week"):
        for item in list_data["items"]:
            if recipe_id in item.get("recipe_tags", []):
                ing = next((i for i in recipe["ingredients"] if i["item"].lower() == item["item"].lower()), None)
                if ing:
                    old_contrib = round(float(ing.get("qty", 1)) * old_ratio, 2)
                    new_contrib = round(float(ing.get("qty", 1)) * new_ratio, 2)
                    item["qty"] = round(max(0, float(item.get("qty", 1)) - old_contrib + new_contrib), 2)

    for i, r in enumerate(recipes_data["recipes"]):
        if r["id"] == recipe_id:
            recipes_data["recipes"][i] = recipe

    save_json("recipes.json", recipes_data)
    save_json("list.json", list_data)
    return jsonify({"success": True, "servings": new_servings})

@app.route("/api/recipes/<recipe_id>/image", methods=["GET"])
def get_recipe_image(recipe_id):
    """Serve recipe photo."""
    import base64
    from flask import send_file
    img_path = os.path.join(UPLOAD_FOLDER, f"{recipe_id}.jpg")
    if os.path.exists(img_path):
        return send_file(img_path, mimetype="image/jpeg")
    return jsonify({"error": "No image"}), 404


# ─── Settings ─────────────────────────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_json("settings.json"))

@app.route("/api/settings", methods=["PUT"])
def update_settings():
    data = load_json("settings.json")
    data.update(request.json)
    save_json("settings.json", data)
    return jsonify(data)

@app.route("/api/settings/categories", methods=["POST"])
def add_category():
    data = load_json("settings.json")
    cat = request.json.get("category", "").strip()
    if cat and cat not in data.get("categories", []):
        data.setdefault("categories", []).append(cat)
        save_json("settings.json", data)
    return jsonify(data["categories"])

@app.route("/api/settings/categories/<cat>", methods=["DELETE"])
def delete_category(cat):
    data = load_json("settings.json")
    data["categories"] = [c for c in data.get("categories", []) if c != cat]
    save_json("settings.json", data)
    return jsonify(data["categories"])


# ─── Analytics ────────────────────────────────────────────────────────────────

@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    return jsonify(load_json("history.json"))

@app.route("/api/analytics/shop", methods=["POST"])
def record_shop():
    history = load_json("history.json")
    shop = request.json
    shop["id"] = str(uuid.uuid4())
    shop["date"] = datetime.now().isoformat()
    history["shops"].append(shop)
    history["total_spent"] = round(history.get("total_spent", 0) + shop.get("total", 0), 2)
    history["total_saved"] = round(history.get("total_saved", 0) + shop.get("saved", 0), 2)
    save_json("history.json", history)
    return jsonify(shop)


# ─── Aldi List ────────────────────────────────────────────────────────────────

@app.route("/api/aldi-list", methods=["GET"])
def get_aldi_list():
    return jsonify(load_json("aldi_list.json"))

@app.route("/api/aldi-list", methods=["POST"])
def set_aldi_list():
    data = request.json
    data["created"] = datetime.now().isoformat()
    data["active"] = True
    save_json("aldi_list.json", data)
    return jsonify(data)

@app.route("/api/aldi-list/toggle/<item_id>", methods=["POST"])
def toggle_aldi_item(item_id):
    data = load_json("aldi_list.json")
    for item in data.get("items", []):
        if item["id"] == item_id:
            item["checked"] = not item.get("checked", False)
            break
    save_json("aldi_list.json", data)
    return jsonify(data)

@app.route("/api/aldi-list/clear", methods=["POST"])
def clear_aldi_list():
    data = {"active": False, "items": [], "created": None, "shop_option": None}
    save_json("aldi_list.json", data)
    return jsonify(data)


# ─── Shop ─────────────────────────────────────────────────────────────────────

@app.route("/api/shop/prepare", methods=["POST"])
def prepare_shop():
    from compare import consolidate_items
    from claude_helper import check_pantry_items, generate_clarifications
    list_data = load_json("list.json")
    history = load_json("history.json")
    active_items = [i for i in list_data["items"] if i.get("included", True)]
    consolidated = consolidate_items(active_items)
    recipe_pantry = [i for i in consolidated if i.get("is_pantry") and "recipe" in i.get("sources", [])]
    pantry_questions = check_pantry_items(recipe_pantry, history.get("shops", []))
    clarifications = generate_clarifications(consolidated, history.get("shops", []))
    return jsonify({
        "items": consolidated,
        "pantry_questions": pantry_questions,
        "clarifications": clarifications,
        "item_count": len(consolidated)
    })

@app.route("/api/shop/prices", methods=["POST"])
def get_prices():
    from scraper import search_all_stores, get_delivery_fees
    from compare import calculate_options
    payload = request.json
    items = payload.get("items", [])
    settings = load_json("settings.json")
    priced_items = []
    not_found = []
    for item in items:
        prices = search_all_stores(item["item"])
        priced_item = {**item, "woolworths": prices.get("woolworths"), "coles": prices.get("coles"), "aldi": prices.get("aldi")}
        priced_items.append(priced_item)
        if not any([prices.get("woolworths"), prices.get("coles"), prices.get("aldi")]):
            not_found.append(item["item"])
    delivery_fees = get_delivery_fees(settings)
    options = calculate_options(priced_items, delivery_fees, settings)
    return jsonify({"options": options, "priced_items": priced_items, "not_found": not_found})

@app.route("/api/shop/specials", methods=["POST"])
def get_specials():
    from scraper import check_for_specials
    from claude_helper import suggest_bulk_buys
    items = request.json.get("items", [])
    settings = load_json("settings.json")
    specials = check_for_specials(items)
    suggestions = suggest_bulk_buys(specials, settings)
    return jsonify({"specials": specials, "suggestions": suggestions})

@app.route("/api/shop/prepare-cart", methods=["POST"])
def prepare_cart():
    """
    Prepare cart links and lists for Coles/Woolworths (options B+C).
    Returns deep links (C) and formatted reference lists (B) for each store.
    """
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
        aldi_items = [{
            "id": str(uuid.uuid4()),
            "item": i.get("item", ""),
            "qty": i.get("qty", 1),
            "unit": i.get("unit", ""),
            "details": i.get("details", ""),
            "price": (i.get("aldi") or {}).get("price"),
            "checked": False
        } for i in items]
        # Save Aldi list persistently
        save_json("aldi_list.json", {
            "active": True,
            "items": aldi_items,
            "created": datetime.now().isoformat(),
            "shop_option": option.get("label", "")
        })
        result["aldi"] = {
            "items": aldi_items,
            "item_count": len(aldi_items)
        }

    return jsonify(result)

@app.route("/api/shop/complete", methods=["POST"])
def complete_shop():
    payload = request.json
    option = payload.get("option", {})
    settings = load_json("settings.json")
    history = load_json("history.json")
    today = datetime.now().isoformat()

    cheapest_single = payload.get("cheapest_single_store", option.get("total", 0))
    saved = round(max(cheapest_single - option.get("total", 0), 0), 2)
    rewards_saved = round(option.get("subtotal", 0) * 0.1, 2) if option.get("rewards_plus_applied") else 0

    shop_record = {
        "id": str(uuid.uuid4()),
        "date": today,
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

    # Update purchase counts
    list_data = load_json("list.json")
    purchased_ids = {i["id"] for i in payload.get("items", [])}
    for item in list_data["items"]:
        if item["id"] in purchased_ids:
            item["purchase_count"] = item.get("purchase_count", 0) + 1
            item["last_purchased"] = today
    save_json("list.json", list_data)

    # Update Rewards Plus
    if option.get("rewards_plus_applied"):
        settings["rewards_plus_last_used"] = today
        settings["rewards_plus_active"] = False
        settings["rewards_plus_code"] = ""
        save_json("settings.json", settings)

    # Update recipe cook counts, reset for next week
    recipes_data = load_json("recipes.json")
    for recipe in recipes_data["recipes"]:
        if recipe.get("active_this_week"):
            recipe["cook_count"] = recipe.get("cook_count", 0) + 1
            recipe["last_cooked"] = today
            recipe["active_this_week"] = False
            recipe["this_week_servings"] = recipe["base_servings"]
    save_json("recipes.json", recipes_data)

    return jsonify({"success": True, "shop": shop_record})


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Handle HA ingress base path
    ingress_path = os.environ.get("INGRESS_PATH", "")
    if ingress_path:
        app.config["APPLICATION_ROOT"] = ingress_path
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)
    print(f"\n🛒 Smart Cart running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
