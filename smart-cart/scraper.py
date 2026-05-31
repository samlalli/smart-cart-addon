"""
scraper.py — Price scraping using requests + BeautifulSoup.
No Playwright required — works on HA Green (ARM64).
"""
import re
import json
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}


def parse_price(text: str) -> float | None:
    """Extract float price from a string like '$3.50' or '3.50'."""
    if not text:
        return None
    match = re.search(r'[\d]+\.[\d]{2}|[\d]+', text.replace(",", ""))
    if match:
        return float(match.group())
    return None


def search_woolworths(item_name: str) -> dict | None:
    """Search Woolworths API for an item."""
    try:
        url = f"https://www.woolworths.com.au/apis/ui/Search/products?searchTerm={requests.utils.quote(item_name)}&pageNumber=1&pageSize=5&sortType=TraderRelevance"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        products = data.get("Products", [])
        if not products:
            return None
        # Get first result
        product = products[0]
        info = product.get("Products", [{}])[0] if product.get("Products") else product
        name = info.get("DisplayName") or info.get("Name", item_name)
        price = info.get("Price") or info.get("WasPrice")
        if price is None:
            return None
        # Check if on special
        was_price = info.get("WasPrice")
        on_special = was_price is not None and was_price > float(price)
        return {
            "name": name,
            "price": float(price),
            "was_price": float(was_price) if was_price else None,
            "on_special": on_special,
            "store": "Woolworths",
            "stockcode": info.get("Stockcode", ""),
        }
    except Exception as e:
        print(f"Woolworths search error for '{item_name}': {e}")
        return None


def search_coles(item_name: str) -> dict | None:
    """Search Coles API for an item."""
    try:
        url = f"https://www.coles.com.au/api/2.0.0/market/products?q={requests.utils.quote(item_name)}&pageNumber=1&pageSize=5"
        resp = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=10)
        if resp.status_code != 200:
            # Try alternate endpoint
            url2 = f"https://product.coles.com.au/product?q={requests.utils.quote(item_name)}&pageNumber=1&pageSize=5"
            resp = requests.get(url2, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                return None
        data = resp.json()
        results = data.get("results", data.get("catalogEntryView", []))
        if not results:
            return None
        product = results[0]
        name = product.get("name", item_name)
        price_info = product.get("pricing", product.get("price", {}))
        if isinstance(price_info, dict):
            price = price_info.get("now", price_info.get("price"))
            was_price = price_info.get("was")
        else:
            price = price_info
            was_price = None
        if price is None:
            return None
        price = float(str(price).replace("$", ""))
        on_special = was_price is not None
        return {
            "name": name,
            "price": price,
            "was_price": float(str(was_price).replace("$", "")) if was_price else None,
            "on_special": on_special,
            "store": "Coles",
        }
    except Exception as e:
        print(f"Coles search error for '{item_name}': {e}")
        return None


def search_aldi(item_name: str) -> dict | None:
    """
    Search for Aldi pricing via TrolleyChecker or a price comparison site.
    Aldi doesn't have a public API so we use a comparison site.
    """
    try:
        url = f"https://www.getpricelist.com.au/search.aspx?q={requests.utils.quote(item_name)}&stores=aldi"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            # Look for price elements
            price_el = soup.find(class_=re.compile(r"price|Price"))
            name_el = soup.find(class_=re.compile(r"name|title|product", re.I))
            if price_el:
                price = parse_price(price_el.get_text())
                name = name_el.get_text(strip=True) if name_el else item_name
                if price:
                    return {"name": name, "price": price, "was_price": None, "on_special": False, "store": "Aldi"}

        # Fallback: try mysupermarket or grocer.com.au
        url2 = f"https://www.grocer.com.au/search?q={requests.utils.quote(item_name)}&store=aldi"
        resp2 = requests.get(url2, headers=HEADERS, timeout=10)
        if resp2.status_code == 200:
            soup2 = BeautifulSoup(resp2.text, "lxml")
            price_el = soup2.find(class_=re.compile(r"price", re.I))
            if price_el:
                price = parse_price(price_el.get_text())
                if price:
                    return {"name": item_name, "price": price, "was_price": None, "on_special": False, "store": "Aldi"}

        return None
    except Exception as e:
        print(f"Aldi search error for '{item_name}': {e}")
        return None


def search_all_stores(item_name: str) -> dict:
    """Search all three stores for an item."""
    result = {
        "item": item_name,
        "woolworths": None,
        "coles": None,
        "aldi": None,
        "error": None
    }
    # Small delay between requests to be polite
    result["woolworths"] = search_woolworths(item_name)
    time.sleep(0.3)
    result["coles"] = search_coles(item_name)
    time.sleep(0.3)
    result["aldi"] = search_aldi(item_name)
    return result


def get_delivery_fees(settings: dict) -> dict:
    """Return delivery fees based on subscription settings and order total."""
    return {
        "woolworths": 0.0 if settings.get("woolworths_delivery_sub") else 15.0,
        "coles": 0.0 if settings.get("coles_plus") else 13.0,
        "aldi": 0.0
    }


def check_for_specials(items: list) -> list:
    """Check which cupboard items are on special at Woolworths or Coles."""
    specials = []
    for item in items:
        if not item.get("is_cupboard"):
            continue
        try:
            w = search_woolworths(item["item"])
            if w and w.get("on_special") and w.get("was_price"):
                specials.append({
                    "item": item["item"],
                    "item_id": item.get("id"),
                    "store": "Woolworths",
                    "special_price": w["price"],
                    "normal_price": w["was_price"],
                    "is_cupboard": True
                })
            time.sleep(0.3)
            c = search_coles(item["item"])
            if c and c.get("on_special") and c.get("was_price"):
                specials.append({
                    "item": item["item"],
                    "item_id": item.get("id"),
                    "store": "Coles",
                    "special_price": c["price"],
                    "normal_price": c["was_price"],
                    "is_cupboard": True
                })
            time.sleep(0.3)
        except Exception as e:
            print(f"Specials check error for {item['item']}: {e}")
    return specials


def build_woolworths_cart_url(items: list) -> str:
    """
    Build a Woolworths deep link that adds items to cart.
    Uses Woolworths' barcode/stockcode based cart URL where possible.
    Falls back to search URL for items without a stockcode.
    """
    # Woolworths doesn't have a public multi-item cart deep link
    # Best option: search URL for first item, with list for reference
    if not items:
        return "https://www.woolworths.com.au"
    first = items[0]
    stockcode = first.get("stockcode", "")
    if stockcode:
        return f"https://www.woolworths.com.au/shop/productdetails/{stockcode}"
    return f"https://www.woolworths.com.au/shop/search/products?searchTerm={requests.utils.quote(first['item'])}"


def build_coles_cart_url(items: list) -> str:
    """Build a Coles search URL for the first item."""
    if not items:
        return "https://www.coles.com.au"
    first = items[0]
    return f"https://www.coles.com.au/search?q={requests.utils.quote(first['item'])}"


def format_store_list(items: list, store: str) -> list:
    """
    Format items for a store reference list (fallback to B when deep links unavailable).
    Returns list of dicts with item, qty, unit, details, price.
    """
    formatted = []
    for item in items:
        store_data = item.get(store.lower(), {}) or {}
        formatted.append({
            "item": item.get("item", ""),
            "qty": item.get("qty", 1),
            "unit": item.get("unit", ""),
            "details": item.get("details", ""),
            "price": store_data.get("price"),
            "matched_name": store_data.get("name", ""),
            "on_special": store_data.get("on_special", False),
        })
    return formatted
