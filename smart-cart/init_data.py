"""init_data.py — Creates default data files on first run."""
import os, json

DATA_DIR = os.environ.get("DATA_DIR", "/data/smart-cart")
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULTS = {
    "list.json": {"items": []},
    "recipes.json": {"recipes": []},
    "history.json": {"shops": [], "total_saved": 0, "total_spent": 0},
    "aldi_list.json": {"active": False, "items": [], "created": None, "shop_option": None},
    "price_history.json": {},
    "settings.json": {
        "preferred_delivery_window": "morning",
        "everyday_rewards": False,
        "flybuys": False,
        "woolworths_delivery_sub": False,
        "coles_plus": False,
        "rewards_plus_active": False,
        "rewards_plus_code": "",
        "rewards_plus_last_used": None,
        "include_woolworths": True,
        "include_coles": True,
        "include_aldi": True,
        "woolworths_store_id": "",
        "woolworths_store_name": "",
        "coles_store_id": "",
        "coles_store_name": "",
        "aldi_store_name": "",
        "aldi_doordash_store_id": "",
        "aldi_doordash_store_name": "",
        "theme": "dark",
        "font_size": "medium",
        "categories": [
            "Fruit & Veg", "Meat", "Seafood", "Deli", "Dairy & Eggs",
            "Bakery", "Frozen", "Canned & Packaged", "Drinks", "Snacks",
            "Condiments & Sauces", "Baking", "Cleaning", "Personal Care", "Cupboard"
        ]
    }
}

for filename, default in DEFAULTS.items():
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        print(f"Created {filename}")
    elif filename == "settings.json":
        with open(path) as f:
            existing = json.load(f)
        updated = False
        for key, val in default.items():
            if key not in existing:
                existing[key] = val
                updated = True
        if updated:
            with open(path, "w") as f:
                json.dump(existing, f, indent=2)
            print(f"Migrated {filename}")

print("Data initialisation complete.")
