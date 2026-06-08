"""
compare.py — Basket comparison logic for Smart Cart v1.1.0
"""
from claude_helper import convert_units, units_compatible


def format_price(price: float) -> str:
    """Format price with comma separator for values over $1000."""
    if price >= 1000:
        return f"${price:,.2f}"
    return f"${price:.2f}"


def apply_rewards_plus(price: float, active: bool) -> float:
    if active:
        return round(price * 0.9, 2)
    return price


def consolidate_items(items: list) -> list:
    """
    Merge duplicate items. If units are incompatible, create separate entries.
    """
    consolidated = {}

    for item in items:
        key = item["item"].lower().strip()
        qty = float(item.get("qty", 1))
        unit = (item.get("unit") or "").lower().strip()

        if key not in consolidated:
            consolidated[key] = {
                **item,
                "qty": qty,
                "unit": unit,
                "sources": list(item.get("sources", ["manual"])),
                "recipe_tags": list(item.get("recipe_tags", []))
            }
        else:
            existing = consolidated[key]
            existing_unit = (existing.get("unit") or "").lower().strip()

            if units_compatible(existing_unit, unit):
                # Convert and merge
                if existing_unit and unit and existing_unit != unit:
                    try:
                        converted = convert_units(qty, unit, existing_unit)
                        existing["qty"] = round(existing["qty"] + converted, 3)
                    except Exception:
                        # Can't convert — create separate entry
                        alt_key = f"{key}__{unit}"
                        consolidated[alt_key] = {**item, "qty": qty, "unit": unit}
                else:
                    existing["qty"] = round(existing["qty"] + qty, 3)
            else:
                # Incompatible units — separate entry
                alt_key = f"{key}__{unit}"
                if alt_key not in consolidated:
                    consolidated[alt_key] = {**item, "qty": qty, "unit": unit}

            # Merge tags and sources
            for tag in item.get("recipe_tags", []):
                if tag not in existing.get("recipe_tags", []):
                    existing.setdefault("recipe_tags", []).append(tag)
            for src in item.get("sources", []):
                if src not in existing.get("sources", []):
                    existing.setdefault("sources", []).append(src)

    return list(consolidated.values())


def calculate_options(priced_items: list, delivery_fees: dict, settings: dict) -> list:
    """Calculate all store combination options."""
    rewards_plus = settings.get("rewards_plus_active", False)
    include_w = settings.get("include_woolworths", True)
    include_c = settings.get("include_coles", True)
    include_a = settings.get("include_aldi", True)

    def item_cost(item, store):
        data = item.get(store)
        if not data:
            return None
        # Prefer pack-aware line_total (packs × unit price); fall back to legacy price×qty
        if data.get("line_total") is not None:
            price = float(data["line_total"])
        else:
            price = data["price"] * float(item.get("qty", 1))
        if store == "woolworths":
            price = apply_rewards_plus(price, rewards_plus)
        return round(price, 2)

    def get_fallback_cost(item, excluded):
        for store in ["woolworths", "coles", "aldi"]:
            if store != excluded:
                c = item_cost(item, store)
                if c is not None:
                    return c
        return 0

    def basket_cost(items, store):
        total = 0
        unavail = []
        for item in items:
            cost = item_cost(item, store)
            if cost is None:
                unavail.append(item["item"])
                total += get_fallback_cost(item, store)
            else:
                total += cost
        return round(total, 2), unavail

    def cheapest_split(items, allowed_stores):
        total = 0
        split = {}
        unavail = []
        for item in items:
            best_price = None
            best_store = None
            for store in allowed_stores:
                cost = item_cost(item, store)
                if cost is not None:
                    if best_price is None or cost < best_price:
                        best_price = cost
                        best_store = store
            if best_store:
                total += best_price
                split.setdefault(best_store, []).append({**item, "assigned_price": best_price})
            else:
                unavail.append(item["item"])
        return round(total, 2), split, unavail

    options = []

    # Single store options
    if include_w:
        sub, unavail = basket_cost(priced_items, "woolworths")
        d = delivery_fees.get("woolworths", 15.0)
        options.append({
            "id": "woolworths_only", "label": "All Woolworths",
            "stores": ["woolworths"], "subtotal": sub, "delivery": d,
            "total": round(sub + d, 2), "unavailable": unavail,
            "split": {"woolworths": priced_items},
            "rewards_plus_applied": rewards_plus,
            "notes": "10% Rewards Plus applied" if rewards_plus else ""
        })

    if include_c:
        sub, unavail = basket_cost(priced_items, "coles")
        d = delivery_fees.get("coles", 13.0)
        options.append({
            "id": "coles_only", "label": "All Coles",
            "stores": ["coles"], "subtotal": sub, "delivery": d,
            "total": round(sub + d, 2), "unavailable": unavail,
            "split": {"coles": priced_items},
            "rewards_plus_applied": False, "notes": ""
        })

    if include_a:
        sub, unavail = basket_cost(priced_items, "aldi")
        options.append({
            "id": "aldi_only", "label": "All Aldi (in-store)",
            "stores": ["aldi"], "subtotal": sub, "delivery": 0,
            "total": sub, "unavailable": unavail,
            "split": {"aldi": priced_items},
            "rewards_plus_applied": False,
            "notes": f"{len(unavail)} items unavailable at Aldi" if unavail else "In-store checklist"
        })

    # Split options
    enabled = [s for s, inc in [("woolworths", include_w), ("coles", include_c), ("aldi", include_a)] if inc]

    if include_w and include_a:
        sub, split, unavail = cheapest_split(priced_items, ["woolworths", "aldi"])
        wd = delivery_fees.get("woolworths", 15.0) if "woolworths" in split else 0
        options.append({
            "id": "woolworths_aldi", "label": "Woolworths + Aldi",
            "stores": ["woolworths", "aldi"], "subtotal": sub, "delivery": wd,
            "total": round(sub + wd, 2), "unavailable": unavail, "split": split,
            "rewards_plus_applied": rewards_plus,
            "notes": f"Aldi in-store for {len(split.get('aldi', []))} items"
        })

    if include_c and include_a:
        sub, split, unavail = cheapest_split(priced_items, ["coles", "aldi"])
        cd = delivery_fees.get("coles", 13.0) if "coles" in split else 0
        options.append({
            "id": "coles_aldi", "label": "Coles + Aldi",
            "stores": ["coles", "aldi"], "subtotal": sub, "delivery": cd,
            "total": round(sub + cd, 2), "unavailable": unavail, "split": split,
            "rewards_plus_applied": False,
            "notes": f"Aldi in-store for {len(split.get('aldi', []))} items"
        })

    if include_w and include_c:
        sub, split, unavail = cheapest_split(priced_items, ["woolworths", "coles"])
        wd = delivery_fees.get("woolworths", 15.0) if "woolworths" in split else 0
        cd = delivery_fees.get("coles", 13.0) if "coles" in split else 0
        options.append({
            "id": "coles_woolworths", "label": "Coles + Woolworths Split",
            "stores": ["coles", "woolworths"], "subtotal": sub, "delivery": wd + cd,
            "total": round(sub + wd + cd, 2), "unavailable": unavail, "split": split,
            "rewards_plus_applied": rewards_plus, "notes": "Two deliveries"
        })

    if include_w and include_c and include_a:
        sub, split, unavail = cheapest_split(priced_items, ["woolworths", "coles", "aldi"])
        wd = delivery_fees.get("woolworths", 15.0) if "woolworths" in split else 0
        cd = delivery_fees.get("coles", 13.0) if "coles" in split else 0
        options.append({
            "id": "all_three", "label": "All Three Stores",
            "stores": ["woolworths", "coles", "aldi"], "subtotal": sub, "delivery": wd + cd,
            "total": round(sub + wd + cd, 2), "unavailable": unavail, "split": split,
            "rewards_plus_applied": rewards_plus,
            "notes": "Maximum savings — Aldi in-store required"
        })

    options.sort(key=lambda x: x["total"])
    if options:
        options[0]["is_cheapest"] = True

    return options
