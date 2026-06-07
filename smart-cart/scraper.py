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
    """Check if a price is within a reasonable range."""
    if price <= 0:
        return False, "Price is zero or negative"
    if price < 0.20:
        return False, f"Price ${price:.2f} is suspiciously low"
    if price > 150:
        return False, f"Price ${price:.2f} is suspiciously high"
    return True, ""


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
            info = product.get("Products", [{}])[0] if product.get("Products") else product
            name = info.get("DisplayName") or info.get("Name", "")
            price = info.get("Price")
            was_price = info.get("WasPrice")
            stockcode = info.get("Stockcode", "")
            aisle = info.get("AdditionalAttributes", {}).get("aisleName", "")
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
                    "store": "woolworths"
                })
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
            if name and price is not None:
                try:
                    price = float(str(price).replace("$", ""))
                    results.append({
                        "name": name,
                        "price": price,
                        "was_price": float(str(was).replace("$", "")) if was else None,
                        "on_special": was is not None,
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

def pick_best_match(item_name: str, item_details: str, candidates: list, store: str) -> dict | None:
    """Use Claude to pick the best matching product from candidates."""
    if not candidates:
        return None
    if len(candidates) == 1:
        ok, _ = sanity_check(candidates[0]["price"], item_name)
        return candidates[0] if ok else None

    try:
        import requests as http_req
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            # Fallback: pick cheapest passing sanity check
            return _pick_cheapest(candidates, item_name)

        prompt = f"""You are helping match a shopping list item to a supermarket product.

Shopping list item: "{item_name}"
Details/preferences: "{item_details or 'none'}"

Candidates from {store}:
{json.dumps([{"index": i, "name": c["name"], "price": c["price"]} for i, c in enumerate(candidates)], indent=2)}

Which candidate best matches the shopping list item considering the name and details?
If multiple are equally good matches, prefer the cheapest.
If none are a reasonable match, say none.

Reply with ONLY a JSON object: {{"index": 0, "reason": "brief reason"}} or {{"index": null, "reason": "no match"}}"""

        resp = http_req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 100, "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        if resp.status_code == 200:
            text = resp.json()["content"][0]["text"].strip()
            clean = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(clean)
            idx = result.get("index")
            if idx is not None and 0 <= idx < len(candidates):
                candidate = candidates[idx]
                ok, msg = sanity_check(candidate["price"], item_name)
                if ok:
                    return candidate
                else:
                    print(f"Sanity check failed for {item_name}: {msg}")
                    return _pick_cheapest(candidates, item_name)
    except Exception as e:
        print(f"Claude matching error: {e}")

    return _pick_cheapest(candidates, item_name)


def _pick_cheapest(candidates: list, item_name: str) -> dict | None:
    """Pick cheapest candidate that passes sanity check."""
    valid = [(c, c["price"]) for c in candidates if sanity_check(c["price"], item_name)[0]]
    if not valid:
        return None
    return min(valid, key=lambda x: x[1])[0]


# ── Main search function ──────────────────────────────────────────────────────

def search_all_stores(item: dict, settings: dict = None) -> dict:
    """
    Search all enabled stores for an item.
    Returns best match per store with price history and sanity info.
    """
    if settings is None:
        settings = {}

    item_name = item.get("item", "")
    item_details = item.get("details", "")
    woolworths_store_id = settings.get("woolworths_store_id", "")

    include_woolworths = settings.get("include_woolworths", True)
    include_coles = settings.get("include_coles", True)
    include_aldi = settings.get("include_aldi", True)

    result = {
        "item": item_name,
        "woolworths": None,
        "coles": None,
        "aldi": None,
        "error": None
    }

    if include_woolworths:
        candidates = search_woolworths_raw(item_name, woolworths_store_id)
        match = pick_best_match(item_name, item_details, candidates, "Woolworths")
        if match:
            ok, warning = sanity_check(match["price"], item_name)
            last = get_last_price(item_name, "woolworths")
            match["warning"] = warning if not ok else ""
            match["last_price"] = last
            if ok:
                record_price(item_name, "woolworths", match["price"], match["name"])
            result["woolworths"] = match
        time.sleep(0.3)

    if include_coles:
        candidates = search_coles_raw(item_name)
        match = pick_best_match(item_name, item_details, candidates, "Coles")
        if match:
            ok, warning = sanity_check(match["price"], item_name)
            last = get_last_price(item_name, "coles")
            match["warning"] = warning if not ok else ""
            match["last_price"] = last
            if ok:
                record_price(item_name, "coles", match["price"], match["name"])
            result["coles"] = match
        time.sleep(0.3)

    if include_aldi:
        candidates = search_aldi_raw(item_name)
        match = pick_best_match(item_name, item_details, candidates, "Aldi")
        if match:
            ok, warning = sanity_check(match["price"], item_name)
            last = get_last_price(item_name, "aldi")
            match["warning"] = warning if not ok else ""
            match["last_price"] = last
            if ok:
                record_price(item_name, "aldi", match["price"], match["name"])
            result["aldi"] = match
        time.sleep(0.3)

    # Fallback to price history if no results found
    for store in ["woolworths", "coles", "aldi"]:
        if result[store] is None:
            last = get_last_price(item_name, store)
            if last:
                result[store] = {
                    "name": last.get("product_name", item_name),
                    "price": last["price"],
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


def check_for_specials(items: list, settings: dict = None) -> list:
    """Check which cupboard items are on special."""
    if settings is None:
        settings = {}
    specials = []
    for item in items:
        if not item.get("is_cupboard"):
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
                            "is_cupboard": True
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
                            "is_cupboard": True
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
        formatted.append({
            "item": item.get("item", ""),
            "qty": item.get("qty", 1),
            "unit": item.get("unit", ""),
            "details": item.get("details", ""),
            "category": item.get("category", ""),
            "price": store_data.get("price"),
            "matched_name": store_data.get("name", ""),
            "on_special": store_data.get("on_special", False),
            "aisle": store_data.get("aisle", ""),
            "estimated": store_data.get("estimated", False),
            "warning": store_data.get("warning", ""),
            "last_price": store_data.get("last_price")
        })
    return formatted
