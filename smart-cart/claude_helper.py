"""
claude_helper.py — Claude API integration for Smart Cart v1.1.0
Uses direct HTTP calls for maximum compatibility.
"""
import os
import json
import requests as http_requests
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5"
MODEL_VISION = "claude-sonnet-4-5"

PANTRY_ITEMS = [
    "flour", "sugar", "salt", "pepper", "oil", "olive oil", "vegetable oil",
    "rice", "pasta", "noodles", "bread crumbs", "breadcrumbs", "stock",
    "soy sauce", "fish sauce", "vinegar", "tomato paste", "canned tomatoes",
    "tinned tomatoes", "baking powder", "baking soda", "bicarbonate of soda",
    "cornflour", "cornstarch", "honey", "maple syrup", "vanilla", "spices",
    "herbs", "cumin", "paprika", "turmeric", "cinnamon", "oregano", "thyme",
    "bay leaves", "chilli flakes", "garlic powder", "onion powder",
    "mustard", "worcestershire", "tabasco", "sriracha", "oyster sauce",
    "coconut milk", "canned chickpeas", "canned beans", "lentils",
    "dried fruit", "nuts", "peanut butter", "jam", "vegemite",
    "condensed milk", "evaporated milk", "cocoa powder", "chocolate chips",
    "stock cube", "bouillon", "curry paste", "sesame oil"
]

SMALL_QUANTITY_THRESHOLD = {
    "tsp": 3, "tbsp": 2, "pinch": 999, "dash": 999,
    "ml": 30, "g": 20
}

CATEGORIES = [
    "Fruit & Veg", "Meat", "Seafood", "Deli", "Dairy & Eggs",
    "Bakery", "Frozen", "Canned & Packaged", "Drinks", "Snacks",
    "Condiments & Sauces", "Baking", "Cleaning", "Personal Care", "Cupboard"
]


def call_claude(messages: list, max_tokens: int = 1500, model: str = None) -> str:
    """Call Claude API and return text response."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "your_claude_api_key_here":
        raise ValueError("Claude API key not set")

    response = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": model or MODEL,
            "max_tokens": max_tokens,
            "messages": messages
        },
        timeout=60
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"]


def call_claude_with_image(text: str, image_data: str, media_type: str = "image/jpeg") -> str:
    """Call Claude API with an image."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("Claude API key not set")

    response = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": MODEL_VISION,
            "max_tokens": 2000,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": text}
                ]
            }]
        },
        timeout=90
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"]


def fetch_url_content(url: str) -> str:
    """Fetch readable text content from a URL."""
    try:
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = http_requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        section = (
            soup.find(class_=lambda c: c and "recipe" in c.lower()) or
            soup.find(id=lambda i: i and "recipe" in i.lower()) or
            soup.find("main") or soup.find("article") or soup.body
        )
        text = section.get_text(separator="\n", strip=True) if section else soup.get_text()
        return text[:8000]
    except Exception as e:
        return f"Could not fetch URL: {str(e)}"


def parse_json_response(text: str, expect_list: bool = False) -> any:
    """Parse JSON from Claude response, handling markdown fences."""
    clean = text.replace("```json", "").replace("```", "").strip()
    if expect_list:
        start, end = clean.find("["), clean.rfind("]") + 1
    else:
        start, end = clean.find("{"), clean.rfind("}") + 1
    if start >= 0 and end > start:
        clean = clean[start:end]
    return json.loads(clean)


def is_pantry_item(name: str) -> bool:
    return any(p in name.lower() for p in PANTRY_ITEMS)


def is_small_quantity(qty: float, unit: str) -> bool:
    """Check if this is a minor/small quantity ingredient."""
    unit_lower = (unit or "").lower().strip()
    threshold = SMALL_QUANTITY_THRESHOLD.get(unit_lower)
    if threshold is not None and qty <= threshold:
        return True
    return False


def guess_category(ingredient_name: str) -> str:
    """Guess a shopping category for an ingredient."""
    name = ingredient_name.lower()
    if any(x in name for x in ["chicken", "beef", "pork", "lamb", "mince", "steak", "bacon", "sausage"]):
        return "Meat"
    if any(x in name for x in ["fish", "salmon", "tuna", "prawn", "seafood", "shrimp"]):
        return "Seafood"
    if any(x in name for x in ["milk", "cream", "butter", "cheese", "yoghurt", "yogurt", "egg"]):
        return "Dairy & Eggs"
    if any(x in name for x in ["apple", "banana", "tomato", "onion", "garlic", "lettuce", "carrot",
                                  "potato", "capsicum", "zucchini", "mushroom", "spinach", "broccoli",
                                  "lemon", "lime", "orange", "avocado", "cucumber", "celery"]):
        return "Fruit & Veg"
    if any(x in name for x in ["bread", "roll", "bun", "loaf", "tortilla", "pita"]):
        return "Bakery"
    if any(x in name for x in ["frozen", "ice cream"]):
        return "Frozen"
    if any(x in name for x in ["can", "tin", "jar", "pasta", "rice", "noodle", "cereal"]):
        return "Canned & Packaged"
    if any(x in name for x in ["sauce", "oil", "vinegar", "mustard", "ketchup", "mayo", "dressing"]):
        return "Condiments & Sauces"
    if any(x in name for x in ["flour", "sugar", "baking", "cocoa", "vanilla", "yeast"]):
        return "Baking"
    if any(x in name for x in ["juice", "water", "drink", "cola", "beer", "wine", "coffee", "tea"]):
        return "Drinks"
    if is_pantry_item(name):
        return "Cupboard"
    return ""


EXTRACTION_PROMPT = """Extract the recipe from this content. Focus on what needs to be PURCHASED at a supermarket.

For each ingredient, think like a shopper:
- "diced chicken" → item: "chicken breast", details: "fresh or frozen, diced or ask butcher"
- "2 cloves garlic, crushed" → item: "garlic", qty: 1, unit: "bulb", details: "fresh"
- "salt to taste" → is_pantry: true (skip for shopping)
- "1 can crushed tomatoes" → item: "crushed tomatoes", qty: 1, unit: "400g can", details: "crushed"
- "fresh or frozen peas" → item: "peas", details: "fresh or frozen 500g bag"
- "olive oil" → is_pantry: true

Details should describe WHAT TO BUY (size, fresh/frozen, brand type) NOT how to prepare it.

Available categories: {categories}

Return ONLY a JSON object, no other text:
{{
  "name": "Recipe Name",
  "servings": 4,
  "ingredients": [
    {{
      "item": "ingredient name for shopping",
      "qty": 1,
      "unit": "g/kg/ml/L/can/bunch/etc",
      "details": "shopping details — size, fresh/frozen, type",
      "is_pantry": false,
      "is_small_qty": false,
      "category": "one of the available categories"
    }}
  ],
  "notes": "any useful cooking notes"
}}

Mark is_pantry: true for: oils, spices, herbs, condiments, flour, sugar, stock, sauces, canned goods you'd normally have.
Mark is_small_qty: true for: pinches, dashes, small tbsp/tsp amounts of things (e.g. 1 tsp cumin — already in pantry).
For vague quantities like "a handful", estimate a shopping quantity.""".format(categories=", ".join(CATEGORIES))


def extract_recipe_from_url(url: str) -> dict:
    """Extract recipe from URL by fetching page content then asking Claude."""
    try:
        page_content = fetch_url_content(url)
        prompt = f"{EXTRACTION_PROMPT}\n\nURL: {url}\n\nPage content:\n{page_content}"
        text = call_claude([{"role": "user", "content": prompt}], max_tokens=2000, model=MODEL_VISION)
        return parse_json_response(text)
    except Exception as e:
        return {"error": str(e)}


def extract_recipe_from_image(image_data: str, media_type: str = "image/jpeg") -> dict:
    """Extract recipe from a cookbook photo using Claude Vision."""
    try:
        text = call_claude_with_image(EXTRACTION_PROMPT, image_data, media_type)
        return parse_json_response(text)
    except Exception as e:
        return {"error": str(e)}


def generate_clarifications(items: list, purchase_history: list) -> list:
    """Generate clarifying questions for ambiguous items."""
    try:
        prompt = f"""Review this shopping list and identify items that genuinely need clarification before shopping.

Shopping list:
{json.dumps(items, indent=2)}

Return ONLY a JSON array, no other text:
[
  {{
    "item_id": "item id",
    "item_name": "item name",
    "question": "specific question",
    "options": ["option 1", "option 2", "option 3"],
    "field_to_update": "details"
  }}
]

Only flag genuinely ambiguous items like:
- "cream" (thickened? sour? pouring?)
- "mince" (beef? pork? chicken?)
- "bread" (white? wholegrain? sourdough?)

Do NOT flag items with clear details already. Return [] if nothing needs clarification."""

        text = call_claude([{"role": "user", "content": prompt}])
        return parse_json_response(text, expect_list=True)
    except Exception:
        return []


def check_pantry_items(recipe_items: list, purchase_history: list) -> list:
    """Determine which pantry items to ask about based on purchase history."""
    try:
        pantry_items = [i for i in recipe_items if i.get("is_pantry") or i.get("is_small_qty")]
        if not pantry_items:
            return []

        prompt = f"""These pantry/minor items are needed for recipes. Based on purchase history, which should we ask the user about?

Items needed:
{json.dumps(pantry_items, indent=2)}

Purchase history (recent shops):
{json.dumps(purchase_history[-10:] if len(purchase_history) > 10 else purchase_history, indent=2)}

Return ONLY a JSON array:
[
  {{
    "item": "item name",
    "last_purchased": "date or null",
    "reason": "brief reason e.g. 'last bought 8 weeks ago'"
  }}
]

Logic: skip if purchased within 3 weeks. Ask if 3-8 weeks ago. Definitely ask if 8+ weeks or never purchased.
Return [] if nothing to ask."""

        text = call_claude([{"role": "user", "content": prompt}])
        return parse_json_response(text, expect_list=True)
    except Exception:
        return []


def suggest_bulk_buys(specials: list, settings: dict) -> list:
    """Suggest bulk buying opportunities for shelf-stable items on special."""
    try:
        if not specials:
            return []
        prompt = f"""Analyse these on-special items and suggest bulk-buying opportunities.

These are all shelf-stable / non-perishable items currently on special:
{json.dumps(specials, indent=2)}

Woolworths Rewards Plus active: {settings.get('rewards_plus_active', False)} (10% off)

Suggest stocking up on items that store well: canned and packaged goods (canned tomatoes, beans,
chickpeas, coconut milk), pasta, rice, noodles, oils, sauces, baking staples, long-life drinks, etc.
These are exactly the things worth buying extra of when discounted.

Return ONLY a JSON array:
[
  {{
    "item": "item name",
    "store": "store name",
    "normal_price": 0.00,
    "special_price": 0.00,
    "suggested_qty": 2,
    "saving": 0.00,
    "reason": "brief explanation e.g. 'stocks well, $1.60 off each'",
    "is_rewards_plus_suggestion": false
  }}
]

Suggest any shelf-stable item with a real saving (>$0.50 per extra unit). Skip perishables. Return [] if none."""

        text = call_claude([{"role": "user", "content": prompt}])
        return parse_json_response(text, expect_list=True)
    except Exception:
        return []


def convert_units(qty: float, from_unit: str, to_unit: str) -> float:
    """Convert between common units."""
    conversions = {
        ("g", "kg"): 0.001, ("kg", "g"): 1000,
        ("ml", "l"): 0.001, ("l", "ml"): 1000,
        ("tsp", "tbsp"): 0.333, ("tbsp", "tsp"): 3,
        ("cup", "ml"): 250, ("ml", "cup"): 0.004,
        ("tbsp", "ml"): 15, ("tsp", "ml"): 5,
    }
    key = (from_unit.lower().strip(), to_unit.lower().strip())
    return qty * conversions.get(key, 1)


def units_compatible(unit1: str, unit2: str) -> bool:
    """Check if two units can be meaningfully combined."""
    weight = {"g", "kg", "oz", "lb"}
    volume = {"ml", "l", "cup", "tbsp", "tsp", "fl oz"}
    count = {"piece", "unit", "bunch", "head", "clove", "slice", "rasher", ""}

    def group(u):
        u = u.lower().strip()
        if u in weight: return "weight"
        if u in volume: return "volume"
        if u in count: return "count"
        return u  # treat unknown units as their own group

    return group(unit1) == group(unit2)
