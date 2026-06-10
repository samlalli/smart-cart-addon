"""
scraper.py — Price scraping for Smart Cart v1.1.0
Uses Woolworths/Coles internal APIs + TrolleyChecker for Aldi.
Claude selects best match from top 5 results.
Includes price history tracking and sanity checking.
"""
import re
import json
import time
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-AU,en;q=0.9",
}

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
PRICE_HISTORY_FILE = os.path.join(DATA_DIR, "price_history.json")


# ── Price history ──────────────────────────────────────────────────────────────

def load_price_history():
    try:
        with open(PRICE_HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_price_history(history):
    with open(PRICE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def record_price(item_name: str, store: str, price: float, product_name: str):
    """Record a price lookup result for future reference."""
    history = load_price_history()
    key = item_name.lower().strip()
    if key not in history:
        history[key] = {}
    history[key][store] = {
        "price": price,
        "product_name": product_name,
        "date": datetime.now().isoformat()
    }
    save_price_history(history)

def get_last_price(item_name: str, store: str) -> dict | None:
    """Get the last known price for an item at a store."""
    history = load_price_history()
    key = item_name.lower().strip()
    return history.get(key, {}).get(store)


# ── Sanity check ───────────────────────────────────────────────────────────────

def sanity_check(price: float, item_name: str) -> tuple[bool, str]:
    """Check if a price is within a reasonable range (per pack/unit)."""
    if price <= 0:
        return False, "Price is zero or negative"
    if price < 0.20:
        return False, f"Price ${price:.2f} is suspiciously low"
    if price > 150:
        return False, f"Price ${price:.2f} is suspiciously high"
    return True, ""


# ── Pack size parsing ────────────────────────────────────────────────────────

import re as _re
import math as _math

# Weight/volume units we can compare against a required quantity
_PACK_UNIT_GROUPS = {
    "g": ("weight", 1.0), "kg": ("weight", 1000.0),
    "ml": ("volume", 1.0), "l": ("volume", 1000.0), "litre": ("volume", 1000.0),
}

def parse_pack_size(product_name: str):
    """
    Extract pack size from a product name.
    Returns (amount_in_base_units, group, raw_label) or None.
    e.g. "Mushrooms Cups Punnet 200g" -> (200.0, "weight", "200g")
         "Full Cream Milk 2L"         -> (2000.0, "volume", "2L")
         "Eggs 12 pack"               -> (12.0, "count", "12 pack")
    """
    if not product_name:
        return None
    name = product_name.lower()

    # Weight / volume e.g. 200g, 1.5kg, 2l, 500ml
    m = _re.search(r'(\d+(?:\.\d+)?)\s*(kg|g|ml|l|litre)\b', name)
    if m:
        amount = float(m.group(1))
        unit = m.group(2)
        group, factor = _PACK_UNIT_GROUPS.get(unit, (None, 1.0))
        if group:
            return (amount * factor, group, f"{m.group(1)}{unit}")

    # Count packs e.g. "12 pack", "6pk", "x4"
    m = _re.search(r'(\d+)\s*(?:pack|pk|pieces|pce|ea|x)\b', name)
    if m:
        return (float(m.group(1)), "count", f"{m.group(1)} pack")

    return None


def _required_in_group(qty: float, unit: str, group: str):
    """Convert a required qty+unit into the same base units as a pack group, or None if incompatible."""
    u = (unit or "").lower().strip()
    info = _PACK_UNIT_GROUPS.get(u)
    if info and info[0] == group:
        return qty * info[1]
    return None


def calc_packs_needed(required_qty: float, required_unit: str, product_name: str):
    """
    Work out how many packs to buy.
    Returns dict: {packs, pack_label, note} — packs is always a whole number >= 1.
    Falls back to 1 pack when units can't be reconciled.
    """
    try:
        required_qty = float(required_qty or 1)
    except (TypeError, ValueError):
        required_qty = 1.0
    pack = parse_pack_size(product_name)
    unit_l = (required_unit or "").lower().strip()
    is_weight_or_volume_unit = unit_l in _PACK_UNIT_GROUPS or unit_l in ("cup", "cups", "tbsp", "tsp", "fl oz", "oz", "lb")

    if not pack:
        # Product has no parseable pack size. If the shopper's unit is a count-style
        # unit (each, bunch, head, etc — anything that isn't weight/volume),
        # buy ceil(qty); otherwise we can't determine packs, so buy 1.
        if not is_weight_or_volume_unit:
            return {"packs": max(1, _math.ceil(required_qty)), "pack_label": "", "note": ""}
        return {"packs": 1, "pack_label": "", "note": "1 (check quantity)"}

    pack_amount, group, pack_label = pack

    if group == "count":
        # Required qty is itself a count of items
        packs = max(1, _math.ceil(required_qty / pack_amount)) if pack_amount else 1
        return {"packs": packs, "pack_label": pack_label,
                "note": f"{packs} × {pack_label}" if packs > 1 else pack_label}

    # weight/volume — convert required into same base units
    required_base = _required_in_group(required_qty, required_unit, group)
    if required_base is None:
        # Units incompatible (e.g. recipe says "1.5 cups", pack is grams).
        # If the shopper's unit is count-style, buy ceil(qty) of the pack;
        # otherwise buy 1 and flag for checking.
        if not is_weight_or_volume_unit and unit_l:
            packs = max(1, _math.ceil(required_qty))
            return {"packs": packs, "pack_label": pack_label,
                    "note": f"{packs} × {pack_label}" if packs > 1 else pack_label}
        return {"packs": 1, "pack_label": pack_label,
                "note": f"1 × {pack_label} (check quantity)"}

    packs = max(1, _math.ceil(required_base / pack_amount))
    return {"packs": packs, "pack_label": pack_label,
            "note": f"{packs} × {pack_label}" if packs > 1 else pack_label}


# ── Search query builder ──────────────────────────────────────────────────────

# Product descriptors worth adding to a search query (narrow the result set)
_DESCRIPTOR_KEYWORDS = (
    "thigh", "breast", "fillet", "drumstick", "wing", "mince", "diced", "whole",
    "fresh", "frozen", "dried", "canned", "tinned", "leaf", "leaves", "baby",
    "wholemeal", "wholegrain", "white", "brown", "red", "green", "free range",
    "skinless", "boneless", "lean", "extra virgin", "light", "full cream",
    "skim", "low fat", "unsalted", "salted", "plain", "self raising",
)
# Prep instructions to strip — these describe how to cook, not what to buy
_PREP_WORDS = ("crushed", "chopped", "sliced", "minced", "grated", "peeled",
               "to taste", "finely", "roughly", "cubed", "shredded", "halved")

# Disambiguation hints for items whose bare name returns prepared meals etc.
_SEARCH_HINTS = {
    "frozen spinach": "spinach frozen chopped",
    "frozen peas": "peas frozen",
    "frozen corn": "corn kernels frozen",
}

def build_search_query(item_name: str, item_details: str = "") -> str:
    """
    Build a focused search query from the item name plus meaningful descriptors
    in the details field. Strips prep instructions; keeps product descriptors.
    Uses word-boundary matching to avoid false hits ("red" inside "shredded").
    """
    name = (item_name or "").strip()
    details = (item_details or "").lower()

    # Specific disambiguation hints take priority
    key = name.lower().strip()
    if key in _SEARCH_HINTS:
        base = _SEARCH_HINTS[key]
    else:
        base = name

    # Pull useful descriptors out of details using word boundaries,
    # so "red" doesn't match inside "shredded" or "light" inside "slightly".
    extras = []
    base_lower = base.lower()
    for kw in _DESCRIPTOR_KEYWORDS:
        if _re.search(r'\b' + _re.escape(kw) + r'\b', details) and \
           not _re.search(r'\b' + _re.escape(kw) + r'\b', base_lower):
            extras.append(kw)

    # Limit to the two most specific descriptors to avoid over-narrowing
    query = base
    if extras:
        query = f"{base} {' '.join(extras[:2])}"
    return query.strip()


# ── Woolworths ────────────────────────────────────────────────────────────────

def search_woolworths_raw(item_name: str, store_id: str = None) -> list:
    """Search Woolworths internal API, return top 5 raw results."""
    try:
        params = {
            "searchTerm": item_name,
            "pageNumber": 1,
            "pageSize": 5,
            "sortType": "TraderRelevance"
        }
        if store_id:
            params["storeId"] = store_id

        url = "https://www.woolworths.com.au/apis/ui/Search/products"
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []

        data = resp.json()
        products = data.get("Products", [])
        results = []
        for product in products:
            try:
                info = product.get("Products", [{}])[0] if product.get("Products") else product
                name = info.get("DisplayName") or info.get("Name", "")
                price = info.get("Price")
                was_price = info.get("WasPrice")
                stockcode = info.get("Stockcode", "")
                aisle = (info.get("AdditionalAttributes") or {}).get("aisleName", "")
                cup_price = info.get("CupPrice", "")
                cup_measure = info.get("CupMeasure", "")
                if name and price is not None:
                    results.append({
                        "name": name,
                        "price": float(price),
                        "was_price": float(was_price) if was_price else None,
                        "on_special": was_price is not None and float(was_price) > float(price),
                        "stockcode": stockcode,
                        "aisle": aisle,
                        "cup_price": cup_price,
                        "cup_measure": cup_measure,
                        "url": f"https://www.woolworths.com.au/shop/productdetails/{stockcode}" if stockcode else "",
                        "store": "woolworths"
                    })
            except (TypeError, ValueError, KeyError, IndexError):
                continue  # one malformed product shouldn't kill the whole result set
        return results
    except Exception as e:
        print(f"Woolworths search error for '{item_name}': {e}")
        return []


def search_woolworths_stores(suburb_or_postcode: str) -> list:
    """Find Woolworths stores near a suburb or postcode."""
    try:
        url = f"https://www.woolworths.com.au/apis/ui/store/geolocation/{requests.utils.quote(suburb_or_postcode)}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        stores = []
        for s in data.get("Stores", [])[:10]:
            stores.append({
                "id": s.get("StoreId", ""),
                "name": s.get("Name", ""),
                "address": s.get("AddressLine1", "") + " " + s.get("Suburb", ""),
                "suburb": s.get("Suburb", "")
            })
        return stores
    except Exception as e:
        print(f"Woolworths store search error: {e}")
        return []


# ── Coles ────────────────────────────────────────────────────────────────────

def search_coles_raw(item_name: str) -> list:
    """Search Coles internal API, return top 5 raw results."""
    try:
        url = f"https://www.coles.com.au/api/2.0.0/market/products"
        params = {"q": item_name, "pageNumber": 1, "pageSize": 5}
        resp = requests.get(url, params=params, headers={**HEADERS, "Accept": "application/json"}, timeout=10)

        if resp.status_code != 200:
            # Try alternate endpoint
            url2 = f"https://www.coles.com.au/search?q={requests.utils.quote(item_name)}&pageNumber=1"
            resp = requests.get(url2, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                return []
            # Parse HTML response
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            cards = soup.select("[class*='product-tile'], [class*='coles-targeting']")[:5]
            for card in cards:
                name_el = card.select_one("[class*='product-name'], [class*='title']")
                price_el = card.select_one("[class*='price']")
                if name_el and price_el:
                    price_text = re.search(r'[\d.]+', price_el.get_text())
                    if price_text:
                        results.append({
                            "name": name_el.get_text(strip=True),
                            "price": float(price_text.group()),
                            "was_price": None,
                            "on_special": False,
                            "store": "coles"
                        })
            return results

        data = resp.json()
        results_raw = data.get("results", data.get("catalogEntryView", []))
        results = []
        for product in results_raw[:5]:
            name = product.get("name", "")
            pricing = product.get("pricing", {})
            price = pricing.get("now") if isinstance(pricing, dict) else product.get("price")
            was = pricing.get("was") if isinstance(pricing, dict) else None
            slug = product.get("seoToken") or product.get("slug") or ""
            pid = product.get("id") or product.get("productId") or ""
            prod_url = f"https://www.coles.com.au/product/{slug}" if slug else (
                f"https://www.coles.com.au/search?q={requests.utils.quote(name)}" if name else "")
            if name and price is not None:
                try:
                    price = float(str(price).replace("$", ""))
                    results.append({
                        "name": name,
                        "price": price,
                        "was_price": float(str(was).replace("$", "")) if was else None,
                        "on_special": was is not None,
                        "url": prod_url,
                        "store": "coles"
                    })
                except Exception:
                    continue
        return results
    except Exception as e:
        print(f"Coles search error for '{item_name}': {e}")
        return []


def search_coles_stores(suburb_or_postcode: str) -> list:
    """Find Coles stores near a suburb or postcode."""
    try:
        url = f"https://www.coles.com.au/api/2.0.0/stores?q={requests.utils.quote(suburb_or_postcode)}&pageSize=10"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        stores = []
        for s in data.get("stores", data.get("results", []))[:10]:
            stores.append({
                "id": s.get("id", s.get("storeId", "")),
                "name": s.get("name", s.get("storeName", "")),
                "address": s.get("address", {}).get("line1", "") if isinstance(s.get("address"), dict) else s.get("address", ""),
                "suburb": s.get("suburb", "")
            })
        return stores
    except Exception as e:
        print(f"Coles store search error: {e}")
        return []


# ── Aldi via TrolleyChecker ───────────────────────────────────────────────────

def search_aldi_raw(item_name: str) -> list:
    """Search TrolleyChecker for Aldi prices."""
    try:
        url = f"https://www.trolleychecker.com.au/search?q={requests.utils.quote(item_name)}"
        resp = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=12)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        # Find product cards
        cards = soup.select("[class*='product'], [class*='item'], [class*='result']")
        for card in cards[:10]:
            store_el = card.select_one("[class*='store'], [class*='retailer'], img[alt]")
            store_name = ""
            if store_el:
                store_name = (store_el.get("alt") or store_el.get_text(strip=True)).lower()

            if "aldi" not in store_name:
                continue

            name_el = card.select_one("[class*='name'], [class*='title'], h2, h3, p")
            price_el = card.select_one("[class*='price']")

            if name_el and price_el:
                price_match = re.search(r'[\d]+\.[\d]{2}', price_el.get_text())
                if price_match:
                    results.append({
                        "name": name_el.get_text(strip=True),
                        "price": float(price_match.group()),
                        "was_price": None,
                        "on_special": False,
                        "store": "aldi"
                    })

        return results
    except Exception as e:
        print(f"Aldi search error for '{item_name}': {e}")
        return []


# ── Claude matching ───────────────────────────────────────────────────────────

# Words that indicate a prepared dish / different product type. If a candidate
# contains one of these and the shopper's item does NOT, it's almost certainly
# the wrong product (e.g. "frozen spinach" -> "Spinach & Ricotta Ravioli Meal").
_DISH_WORDS = ("ravioli", "lasagne", "lasagna", "pizza", "meal", "soup", "sauce",
               "pie", "quiche", "burger", "nugget", "schnitzel", "kiev", "dumpling",
               "spring roll", "pasta bake", "risotto", "curry", "stir fry", "noodle box",
               "chips", "crisps", "snack", "bar", "biscuit", "cookie", "cake", "muffin",
               "juice", "drink", "smoothie", "yoghurt", "dip", "spread", "seasoning",
               "stock", "gravy", "marinade", "dressing", "flavoured", "flavour")


def _heuristic_filter(item_name: str, candidates: list) -> list:
    """
    Non-AI fallback filter used when the Claude matching call fails.
    Rejects candidates that look like prepared dishes / derivative products
    unless those words appear in the shopper's own item name.
    """
    item_lower = (item_name or "").lower()
    filtered = []
    for c in candidates:
        cname = (c.get("name") or "").lower()
        rejected = False
        for w in _DISH_WORDS:
            if w in cname and w not in item_lower:
                rejected = True
                break
        if not rejected and sanity_check(c["price"], item_name)[0]:
            filtered.append(c)
    return filtered


def pick_valid_matches(item_name: str, item_details: str, candidates: list, store: str) -> list:
    """
    Use Claude to identify ALL candidates that are a genuine match for the item.
    Returns a list of candidate dicts (may be empty). Cost optimisation happens later.
    """
    if not candidates:
        return []
    # Single candidate — still apply the heuristic filter + sanity check
    if len(candidates) == 1:
        return _heuristic_filter(item_name, candidates)

    try:
        import requests as http_req
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            # No Claude — heuristic filter (rejects prepared dishes etc.)
            return _heuristic_filter(item_name, candidates)

        prompt = f"""You are matching a shopping-list item to supermarket products. Be strict.

Shopping list item: "{item_name}"
Details/preferences: "{item_details or 'none'}"

Candidates from {store}:
{json.dumps([{"index": i, "name": c["name"], "price": c["price"]} for i, c in enumerate(candidates)], indent=2)}

STRICT MATCHING RULES:
1. The candidate's PRIMARY product must BE the item — not merely contain it as an ingredient.
   - "frozen spinach" must match a bag of frozen spinach, NOT "Spinach & Ricotta Ravioli".
   - "tomato" must match fresh tomatoes, NOT "tomato sauce" or "tomato soup".
2. Honour form/state qualifiers: fresh vs frozen vs canned vs dried, whole vs sliced. A different form is NOT a match.
3. A raw ingredient is not a prepared meal, a sauce, or a snack version of it.
4. Return ALL candidates that genuinely match — different brands and pack sizes of the same product are all valid matches. Do NOT filter by price; cost is handled separately.
5. If NO candidate genuinely matches, return an empty list.

Reply with ONLY a JSON object listing every matching index:
{{"matches": [0, 2, 3], "reason": "brief reason"}} or {{"matches": [], "reason": "no genuine match"}}"""

        resp = http_req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 150, "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        if resp.status_code == 200:
            text = resp.json()["content"][0]["text"].strip()
            clean = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(clean)
            idxs = result.get("matches", [])
            valid = []
            for idx in idxs:
                if isinstance(idx, int) and 0 <= idx < len(candidates):
                    c = candidates[idx]
                    if sanity_check(c["price"], item_name)[0]:
                        valid.append(c)
            # Defence in depth: even Claude-accepted matches must pass the
            # prepared-dish heuristic (catches occasional misjudgements).
            return _heuristic_filter(item_name, valid) if valid else []
    except Exception as e:
        print(f"Claude matching error: {e}")

    # Fallback — heuristic filter (rejects prepared dishes / derivatives)
    return _heuristic_filter(item_name, candidates)


def _best_by_total_cost(matches: list, required_qty: float, required_unit: str):
    """
    From a list of valid product matches, pick the one with the lowest TOTAL cost
    to fulfil the required quantity (accounting for pack size). Returns (match, pack_info).
    """
    best = None
    best_pack = None
    best_total = None
    for m in matches:
        pack = calc_packs_needed(required_qty, required_unit, m.get("name", ""))
        total = round(float(m["price"]) * pack["packs"], 2)
        if best_total is None or total < best_total:
            best_total = total
            best = m
            best_pack = pack
    return best, best_pack


# Backwards-compatible single-match helper (used by specials check)
def pick_best_match(item_name: str, item_details: str, candidates: list, store: str) -> dict | None:
    matches = pick_valid_matches(item_name, item_details, candidates, store)
    if not matches:
        return None
    best, _ = _best_by_total_cost(matches, 1, "")
    return best


def _pick_cheapest(candidates: list, item_name: str) -> dict | None:
    """Pick cheapest candidate that passes sanity check."""
    valid = [(c, c["price"]) for c in candidates if sanity_check(c["price"], item_name)[0]]
    if not valid:
        return None
    return min(valid, key=lambda x: x[1])[0]


# ── Main search function ──────────────────────────────────────────────────────

def _resolve_store(item_name, item_details, required_qty, required_unit, candidates, store):
    """Match candidates, pick cheapest by total cost, attach pack/price/history info."""
    matches = pick_valid_matches(item_name, item_details, candidates, store.capitalize())
    if not matches:
        return None

    match, pack = _best_by_total_cost(matches, required_qty, required_unit)
    if not match:
        return None

    # Build the alternatives list (for transparency in the breakdown)
    alternatives = []
    for m in matches:
        p = calc_packs_needed(required_qty, required_unit, m.get("name", ""))
        alternatives.append({
            "name": m.get("name", ""),
            "unit_price": float(m["price"]),
            "packs": p["packs"],
            "pack_label": p["pack_label"],
            "total": round(float(m["price"]) * p["packs"], 2),
            "url": m.get("url", "")
        })
    alternatives.sort(key=lambda x: x["total"])

    ok, warning = sanity_check(match["price"], item_name)
    last = get_last_price(item_name, store)
    unit_price = float(match["price"])
    match["warning"] = warning if not ok else ""
    match["last_price"] = last
    match["packs"] = pack["packs"]
    match["pack_label"] = pack["pack_label"]
    match["pack_note"] = pack["note"]
    match["unit_price"] = unit_price
    match["line_total"] = round(unit_price * pack["packs"], 2)
    match["alternatives"] = alternatives[:5]

    if ok:
        record_price(item_name, store, unit_price, match["name"])
    return match


def search_all_stores(item: dict, settings: dict = None) -> dict:
    """
    Search all enabled stores for an item.
    Returns best match per store with pack calc, price history and sanity info.
    """
    if settings is None:
        settings = {}

    item_name = item.get("item", "")
    item_details = item.get("details", "")
    required_qty = item.get("qty", 1)
    required_unit = item.get("unit", "")
    woolworths_store_id = settings.get("woolworths_store_id", "")

    include = {
        "woolworths": settings.get("include_woolworths", True),
        "coles": settings.get("include_coles", True),
        "aldi": settings.get("include_aldi", True),
    }

    result = {"item": item_name, "woolworths": None, "coles": None, "aldi": None, "error": None}

    # Build a focused search query from name + meaningful details
    search_query = build_search_query(item_name, item_details)

    if include["woolworths"]:
        cands = search_woolworths_raw(search_query, woolworths_store_id)
        result["woolworths"] = _resolve_store(item_name, item_details, required_qty, required_unit, cands, "woolworths")
        time.sleep(0.3)

    if include["coles"]:
        cands = search_coles_raw(search_query)
        result["coles"] = _resolve_store(item_name, item_details, required_qty, required_unit, cands, "coles")
        time.sleep(0.3)

    if include["aldi"]:
        cands = search_aldi_raw(search_query)
        result["aldi"] = _resolve_store(item_name, item_details, required_qty, required_unit, cands, "aldi")
        time.sleep(0.3)

    # Fallback to price history if no live result found (included stores only)
    for store in ["woolworths", "coles", "aldi"]:
        if result[store] is None and include.get(store, True):
            last = get_last_price(item_name, store)
            if last:
                pack = calc_packs_needed(required_qty, required_unit, last.get("product_name", item_name))
                unit_price = float(last["price"])
                result[store] = {
                    "name": last.get("product_name", item_name),
                    "price": unit_price,
                    "unit_price": unit_price,
                    "packs": pack["packs"],
                    "pack_label": pack["pack_label"],
                    "pack_note": pack["note"],
                    "line_total": round(unit_price * pack["packs"], 2),
                    "was_price": None,
                    "on_special": False,
                    "store": store,
                    "estimated": True,
                    "estimated_date": last.get("date", ""),
                    "last_price": None,
                    "warning": f"Estimated from last known price ({last.get('date', '')[:10]})"
                }

    return result


def get_delivery_fees(settings: dict) -> dict:
    return {
        "woolworths": 0.0 if settings.get("woolworths_delivery_sub") else 15.0,
        "coles": 0.0 if settings.get("coles_plus") else 13.0,
        "aldi": 0.0
    }


SHELF_STABLE_CATEGORIES = {"canned & packaged", "cupboard", "baking", "condiments & sauces", "drinks"}
SHELF_STABLE_KEYWORDS = ("can", "tin", "tinned", "canned", "jar", "packet", "pasta", "rice",
                          "noodle", "cereal", "flour", "sugar", "oil", "sauce", "stock",
                          "lentil", "bean", "chickpea", "coconut milk", "long life", "uht")

def _is_bulk_eligible(item: dict) -> bool:
    """Eligible for bulk-buy if explicitly cupboard, or a shelf-stable category/keyword."""
    if item.get("is_cupboard"):
        return True
    cat = (item.get("category") or "").lower().strip()
    if cat in SHELF_STABLE_CATEGORIES:
        return True
    name = (item.get("item") or "").lower()
    return any(k in name for k in SHELF_STABLE_KEYWORDS)


def check_for_specials(items: list, settings: dict = None) -> list:
    """Check which shelf-stable items are on special (bulk-buy candidates)."""
    if settings is None:
        settings = {}
    specials = []
    for item in items:
        if not _is_bulk_eligible(item):
            continue
        try:
            if settings.get("include_woolworths", True):
                candidates = search_woolworths_raw(item["item"])
                if candidates:
                    match = pick_best_match(item["item"], item.get("details", ""), candidates, "Woolworths")
                    if match and match.get("on_special") and match.get("was_price"):
                        specials.append({
                            "item": item["item"],
                            "item_id": item.get("id"),
                            "store": "Woolworths",
                            "special_price": match["price"],
                            "normal_price": match["was_price"],
                            "category": item.get("category", ""),
                            "shelf_stable": True
                        })
            time.sleep(0.3)
            if settings.get("include_coles", True):
                candidates = search_coles_raw(item["item"])
                if candidates:
                    match = pick_best_match(item["item"], item.get("details", ""), candidates, "Coles")
                    if match and match.get("on_special") and match.get("was_price"):
                        specials.append({
                            "item": item["item"],
                            "item_id": item.get("id"),
                            "store": "Coles",
                            "special_price": match["price"],
                            "normal_price": match["was_price"],
                            "category": item.get("category", ""),
                            "shelf_stable": True
                        })
            time.sleep(0.3)
        except Exception as e:
            print(f"Specials check error for {item['item']}: {e}")
    return specials


def build_woolworths_cart_url(items: list) -> str:
    if not items:
        return "https://www.woolworths.com.au"
    first = items[0]
    stockcode = first.get("stockcode", "")
    if stockcode:
        return f"https://www.woolworths.com.au/shop/productdetails/{stockcode}"
    return f"https://www.woolworths.com.au/shop/search/products?searchTerm={requests.utils.quote(first['item'])}"


def build_coles_cart_url(items: list) -> str:
    if not items:
        return "https://www.coles.com.au"
    first = items[0]
    return f"https://www.coles.com.au/search?q={requests.utils.quote(first['item'])}"


def format_store_list(items: list, store: str) -> list:
    formatted = []
    for item in items:
        store_data = item.get(store.lower(), {}) or {}
        packs = store_data.get("packs", 1)
        pack_label = store_data.get("pack_label", "")
        unit_price = store_data.get("unit_price", store_data.get("price"))
        line_total = store_data.get("line_total")
        if line_total is None and unit_price is not None:
            line_total = round(float(unit_price) * float(packs or 1), 2)
        # Buy quantity: practical pack count, e.g. "3 × 200g" or just the count
        buy_qty = store_data.get("pack_note") or (f"{packs} × {pack_label}" if pack_label else str(packs))
        formatted.append({
            "item": item.get("item", ""),
            "buy_qty": buy_qty,            # practical purchase quantity
            "packs": packs,
            "pack_label": pack_label,
            "recipe_qty": item.get("qty", 1),
            "recipe_unit": item.get("unit", ""),
            "details": item.get("details", ""),
            "category": item.get("category", ""),
            "unit_price": unit_price,
            "price": line_total,           # line total for this item
            "matched_name": store_data.get("name", ""),
            "url": store_data.get("url", ""),
            "alternatives": store_data.get("alternatives", []),
            "on_special": store_data.get("on_special", False),
            "aisle": store_data.get("aisle", ""),
            "estimated": store_data.get("estimated", False),
            "warning": store_data.get("warning", ""),
            "last_price": store_data.get("last_price")
        })
    return formatted
