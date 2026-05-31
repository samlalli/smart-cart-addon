"""
compare.py — Calculates all store combination options and their costs.
"""


def apply_rewards_plus(price: float, active: bool) -> float:
    """Apply 10% Rewards Plus discount if active."""
    if active:
        return round(price * 0.9, 2)
    return price


def calculate_options(
    priced_items: list,
    delivery_fees: dict,
    settings: dict
) -> list:
    """
    Calculate all 7 store combination options.

    priced_items: list of {
        id, item, qty,
        woolworths: {price, name} or None,
        coles: {price, name} or None,
        aldi: {price, name} or None,
        unavailable: [store names]
    }

    Returns list of option dicts sorted by total cost.
    """
    rewards_plus = settings.get("rewards_plus_active", False)

    def item_cost(item, store):
        """Get cost for an item at a given store."""
        data = item.get(store)
        if not data:
            return None
        price = data["price"] * item.get("qty", 1)
        if store == "woolworths":
            price = apply_rewards_plus(price, rewards_plus)
        return round(price, 2)

    def basket_cost(items, store):
        """Total cost for all items at a given store."""
        total = 0
        unavailable = []
        for item in items:
            cost = item_cost(item, store)
            if cost is None:
                unavailable.append(item["item"])
                # Fall back to most expensive option for unavailable items
                fallback = get_fallback_cost(item, store)
                total += fallback
            else:
                total += cost
        return round(total, 2), unavailable

    def get_fallback_cost(item, excluded_store):
        """Get cost from another store when item unavailable."""
        stores = ["woolworths", "coles", "aldi"]
        for store in stores:
            if store != excluded_store:
                cost = item_cost(item, store)
                if cost is not None:
                    return cost
        return 0

    def cheapest_per_item(items, allowed_stores):
        """Split basket — pick cheapest store per item."""
        total = 0
        split = {}  # store -> [items]
        unavailable = []

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
                if best_store not in split:
                    split[best_store] = []
                split[best_store].append({**item, "assigned_price": best_price})
            else:
                unavailable.append(item["item"])

        return round(total, 2), split, unavailable

    # Calculate all options
    options = []

    # Option 1: All Woolworths
    w_subtotal, w_unavail = basket_cost(priced_items, "woolworths")
    w_delivery = delivery_fees.get("woolworths", 15.0)
    options.append({
        "id": "woolworths_only",
        "label": "All Woolworths",
        "stores": ["woolworths"],
        "subtotal": w_subtotal,
        "delivery": w_delivery,
        "total": round(w_subtotal + w_delivery, 2),
        "unavailable": w_unavail,
        "split": {"woolworths": priced_items},
        "rewards_plus_applied": rewards_plus,
        "notes": "10% Rewards Plus applied" if rewards_plus else ""
    })

    # Option 2: All Coles
    c_subtotal, c_unavail = basket_cost(priced_items, "coles")
    c_delivery = delivery_fees.get("coles", 13.0)
    options.append({
        "id": "coles_only",
        "label": "All Coles",
        "stores": ["coles"],
        "subtotal": c_subtotal,
        "delivery": c_delivery,
        "total": round(c_subtotal + c_delivery, 2),
        "unavailable": c_unavail,
        "split": {"coles": priced_items},
        "rewards_plus_applied": False,
        "notes": ""
    })

    # Option 3: All Aldi (in-store)
    a_subtotal, a_unavail = basket_cost(priced_items, "aldi")
    options.append({
        "id": "aldi_only",
        "label": "All Aldi (in-store)",
        "stores": ["aldi"],
        "subtotal": a_subtotal,
        "delivery": 0,
        "total": a_subtotal,
        "unavailable": a_unavail,
        "split": {"aldi": priced_items},
        "rewards_plus_applied": False,
        "notes": f"{len(a_unavail)} items unavailable at Aldi" if a_unavail else "In-store checklist"
    })

    # Option 4: Woolworths + Aldi split
    wa_total, wa_split, wa_unavail = cheapest_per_item(priced_items, ["woolworths", "aldi"])
    wa_delivery = delivery_fees.get("woolworths", 15.0) if "woolworths" in wa_split else 0
    options.append({
        "id": "woolworths_aldi",
        "label": "Woolworths + Aldi",
        "stores": ["woolworths", "aldi"],
        "subtotal": wa_total,
        "delivery": wa_delivery,
        "total": round(wa_total + wa_delivery, 2),
        "unavailable": wa_unavail,
        "split": wa_split,
        "rewards_plus_applied": rewards_plus,
        "notes": f"Aldi in-store for {len(wa_split.get('aldi', []))} items"
    })

    # Option 5: Coles + Aldi split
    ca_total, ca_split, ca_unavail = cheapest_per_item(priced_items, ["coles", "aldi"])
    ca_delivery = delivery_fees.get("coles", 13.0) if "coles" in ca_split else 0
    options.append({
        "id": "coles_aldi",
        "label": "Coles + Aldi",
        "stores": ["coles", "aldi"],
        "subtotal": ca_total,
        "delivery": ca_delivery,
        "total": round(ca_total + ca_delivery, 2),
        "unavailable": ca_unavail,
        "split": ca_split,
        "rewards_plus_applied": False,
        "notes": f"Aldi in-store for {len(ca_split.get('aldi', []))} items"
    })

    # Option 6: Coles + Woolworths split
    cw_total, cw_split, cw_unavail = cheapest_per_item(priced_items, ["coles", "woolworths"])
    cw_w_delivery = delivery_fees.get("woolworths", 15.0) if "woolworths" in cw_split else 0
    cw_c_delivery = delivery_fees.get("coles", 13.0) if "coles" in cw_split else 0
    options.append({
        "id": "coles_woolworths",
        "label": "Coles + Woolworths Split",
        "stores": ["coles", "woolworths"],
        "subtotal": cw_total,
        "delivery": cw_w_delivery + cw_c_delivery,
        "total": round(cw_total + cw_w_delivery + cw_c_delivery, 2),
        "unavailable": cw_unavail,
        "split": cw_split,
        "rewards_plus_applied": rewards_plus,
        "notes": "Two deliveries"
    })

    # Option 7: All three stores
    all_total, all_split, all_unavail = cheapest_per_item(priced_items, ["woolworths", "coles", "aldi"])
    all_w_delivery = delivery_fees.get("woolworths", 15.0) if "woolworths" in all_split else 0
    all_c_delivery = delivery_fees.get("coles", 13.0) if "coles" in all_split else 0
    options.append({
        "id": "all_three",
        "label": "All Three Stores",
        "stores": ["woolworths", "coles", "aldi"],
        "subtotal": all_total,
        "delivery": all_w_delivery + all_c_delivery,
        "total": round(all_total + all_w_delivery + all_c_delivery, 2),
        "unavailable": all_unavail,
        "split": all_split,
        "rewards_plus_applied": rewards_plus,
        "notes": "Maximum savings — Aldi in-store required"
    })

    # Sort by total cost
    options.sort(key=lambda x: x["total"])

    # Tag cheapest
    if options:
        options[0]["is_cheapest"] = True

    return options


def consolidate_items(items: list) -> list:
    """
    Merge duplicate/equivalent items across recipes and staples.
    Handles unit conversion and quantity addition.
    """
    from claude_helper import convert_units

    # Unit normalisation map
    unit_groups = {
        "weight": ["g", "kg"],
        "volume": ["ml", "l", "cup", "tbsp", "tsp"],
        "count": ["piece", "unit", "bunch", "head", "clove", "slice", "rasher"]
    }

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
                "sources": item.get("sources", [])
            }
        else:
            existing = consolidated[key]
            existing_unit = existing.get("unit", "")

            # Try to convert to same unit
            if existing_unit and unit and existing_unit != unit:
                try:
                    converted_qty = convert_units(qty, unit, existing_unit)
                    existing["qty"] = round(existing["qty"] + converted_qty, 3)
                except Exception:
                    # Can't convert — just add as separate
                    existing["qty"] = existing["qty"] + qty
            else:
                existing["qty"] = round(existing["qty"] + qty, 3)

            # Merge sources
            new_sources = item.get("sources", [])
            for source in new_sources:
                if source not in existing["sources"]:
                    existing["sources"].append(source)

    return list(consolidated.values())
