"""
init_data.py — Creates default data files if they don't exist.
Runs on every startup but only writes files that are missing.
"""
import os
import json

DATA_DIR = os.environ.get("DATA_DIR", "/data/smart-cart")
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULTS = {
    "list.json": {"items": []},
    "recipes.json": {"recipes": []},
    "history.json": {"shops": [], "total_saved": 0, "total_spent": 0},
    "aldi_list.json": {"active": False, "items": [], "created": None, "shop_option": None},
    "settings.json": {
        "split_threshold": int(os.environ.get("SPLIT_THRESHOLD", 10)),
        "preferred_delivery_window": os.environ.get("DELIVERY_WINDOW", "morning"),
        "everyday_rewards": False,
        "flybuys": False,
        "woolworths_delivery_sub": False,
        "coles_plus": False,
        "rewards_plus_active": False,
        "rewards_plus_code": "",
        "rewards_plus_last_used": None,
        "categories": ["Fruit & Veg", "Fridge", "Freezer", "Meat", "Deli", "Bakery", "Cupboard", "Drinks", "Snacks", "Cleaning", "Personal Care"]
    }
}

for filename, default in DEFAULTS.items():
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        print(f"Created {filename}")
    else:
        # Migrate settings — add any missing keys
        if filename == "settings.json":
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
