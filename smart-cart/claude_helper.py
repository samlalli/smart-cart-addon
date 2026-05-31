import os
import json
import requests as http_requests
from dotenv import load_dotenv

load_dotenv()

# Support both old and new Anthropic SDK versions
try:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    SDK_AVAILABLE = True
except Exception as e:
    print(f"Warning: Anthropic SDK issue: {e}")
    SDK_AVAILABLE = False

MODEL = "claude-sonnet-4-5"

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
    "condensed milk", "evaporated milk", "cocoa powder", "chocolate chips"
]


def call_claude(messages: list, max_tokens: int = 1500) -> str:
    """Call Claude API and return text response. Works with any SDK version."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_claude_api_key_here":
        raise ValueError("Claude API key not set in .env file")

    # Use raw HTTP to avoid SDK version issues
    response = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": messages
        },
        timeout=60
    )
    response.raise_for_status()
    data = response.json()
    return data["content"][0]["text"]


def call_claude_with_image(text: str, image_data: str, media_type: str = "image/jpeg") -> str:
    """Call Claude API with an image."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_claude_api_key_here":
        raise ValueError("Claude API key not set in .env file")

    response = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": MODEL,
            "max_tokens": 1500,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data
                        }
                    },
                    {"type": "text", "text": text}
                ]
            }]
        },
        timeout=60
    )
    response.raise_for_status()
    data = response.json()
    return data["content"][0]["text"]


def fetch_url_content(url: str) -> str:
    """Fetch the text content of a recipe URL."""
    try:
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = http_requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove scripts and styles
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        # Try to find recipe-specific content first
        recipe_section = (
            soup.find(class_=lambda c: c and "recipe" in c.lower()) or
            soup.find(id=lambda i: i and "recipe" in i.lower()) or
            soup.find("main") or
            soup.find("article") or
            soup.body
        )
        text = recipe_section.get_text(separator="\n", strip=True) if recipe_section else soup.get_text()
        # Truncate to avoid token limits
        return text[:6000]
    except Exception as e:
        return f"Could not fetch URL: {str(e)}"


def parse_recipe_json(text: str) -> dict:
    """Parse JSON from Claude response, handling markdown code blocks."""
    clean = text.replace("```json", "").replace("```", "").strip()
    # Find JSON object in response
    start = clean.find("{")
    end = clean.rfind("}") + 1
    if start >= 0 and end > start:
        clean = clean[start:end]
    return json.loads(clean)


def is_pantry_item(ingredient_name: str) -> bool:
    """Check if an ingredient is likely a pantry/cupboard item."""
    name_lower = ingredient_name.lower()
    return any(pantry in name_lower for pantry in PANTRY_ITEMS)


def extract_recipe_from_url(url: str) -> dict:
    """Extract recipe ingredients from a URL by fetching content then asking Claude."""
    try:
        # First fetch the actual page content
        page_content = fetch_url_content(url)

        prompt = f"""Extract the recipe from this webpage content.

URL: {url}

Page content:
{page_content}

Return ONLY a JSON object with this exact structure, no other text:
{{
  "name": "Recipe Name",
  "servings": 4,
  "ingredients": [
    {{
      "item": "ingredient name",
      "qty": 1,
      "unit": "kg/g/ml/L/tsp/tbsp/cup/piece/bunch",
      "details": "any specific details like brand, type, size",
      "is_pantry": true
    }}
  ],
  "notes": "any cooking notes"
}}

For is_pantry, mark true for: flour, sugar, oil, spices, canned goods, condiments, sauces, vinegar, stock.
For vague quantities like 'a handful' or 'to taste', estimate a sensible amount.
If you cannot find a recipe in the content, return {{"error": "No recipe found"}}."""

        text = call_claude([{"role": "user", "content": prompt}])
        return parse_recipe_json(text)
    except Exception as e:
        return {"error": str(e)}


def extract_recipe_from_image(image_data: str, media_type: str = "image/jpeg") -> dict:
    """Extract recipe ingredients from a cookbook photo using Claude Vision."""
    try:
        prompt = """Extract the recipe from this cookbook photo.

Return ONLY a JSON object with this exact structure, no other text:
{
  "name": "Recipe Name",
  "servings": 4,
  "ingredients": [
    {
      "item": "ingredient name",
      "qty": 1,
      "unit": "kg/g/ml/L/tsp/tbsp/cup/piece/bunch",
      "details": "any specific details",
      "is_pantry": true
    }
  ],
  "notes": "any cooking notes"
}

For is_pantry, mark true for: flour, sugar, oil, spices, canned goods, condiments.
For vague quantities, estimate a sensible amount.
If you cannot read part of the image, note it in the details field."""

        text = call_claude_with_image(prompt, image_data, media_type)
        return parse_recipe_json(text)
    except Exception as e:
        return {"error": str(e)}


def generate_clarifications(items: list, purchase_history: list) -> list:
    """Generate clarifying questions for ambiguous items."""
    try:
        items_text = json.dumps(items, indent=2)
        history_text = json.dumps(
            purchase_history[-20:] if len(purchase_history) > 20 else purchase_history,
            indent=2
        )
        prompt = f"""Review this shopping list and purchase history. Identify items that need clarification.

Shopping list:
{items_text}

Recent purchase history:
{history_text}

Return ONLY a JSON array, no other text:
[
  {{
    "item_id": "item id from list",
    "item_name": "item name",
    "question": "specific question to ask",
    "options": ["option 1", "option 2", "option 3"],
    "field_to_update": "details"
  }}
]

Only flag genuinely ambiguous items (e.g. 'cream' could be thickened/sour/pouring, 'mince' could be beef/pork/chicken).
Do NOT flag items that already have sufficient details.
Return empty array [] if nothing needs clarification."""

        text = call_claude([{"role": "user", "content": prompt}])
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find("[")
        end = clean.rfind("]") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except Exception:
        return []


def check_pantry_items(recipe_items: list, purchase_history: list) -> list:
    """Determine which pantry items to ask about based on purchase history."""
    try:
        pantry_items = [i for i in recipe_items if i.get("is_pantry")]
        if not pantry_items:
            return []

        prompt = f"""These pantry items are needed for recipes. Based on purchase history, which should we ask the user about?

Pantry items needed:
{json.dumps(pantry_items, indent=2)}

Purchase history:
{json.dumps(purchase_history, indent=2)}

Return ONLY a JSON array, no other text:
[
  {{
    "item": "item name",
    "last_purchased": "date or null",
    "reason": "brief reason e.g. 'last bought 8 weeks ago'"
  }}
]

Logic:
- Never purchased: always ask
- Purchased within 3 weeks: skip (likely still have it)
- Purchased 3-8 weeks ago: ask
- Purchased 8+ weeks ago: definitely ask
Return [] if nothing to ask about."""

        text = call_claude([{"role": "user", "content": prompt}])
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find("[")
        end = clean.rfind("]") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except Exception:
        return []


def suggest_bulk_buys(specials: list, settings: dict) -> list:
    """Suggest bulk buying opportunities for cupboard items on special."""
    try:
        if not specials:
            return []
        prompt = f"""Analyse these specials and suggest bulk buying opportunities.

Specials:
{json.dumps(specials, indent=2)}

Woolworths Rewards Plus active: {settings.get('rewards_plus_active', False)} (10% discount)

Return ONLY a JSON array, no other text:
[
  {{
    "item": "item name",
    "store": "Woolworths/Coles",
    "normal_price": 0.00,
    "special_price": 0.00,
    "suggested_qty": 2,
    "saving": 0.00,
    "reason": "brief explanation",
    "is_rewards_plus_suggestion": false
  }}
]

Only suggest non-perishable/cupboard items. Only if saving is meaningful (>$1 per extra unit).
Return [] if no good opportunities."""

        text = call_claude([{"role": "user", "content": prompt}])
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find("[")
        end = clean.rfind("]") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
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
    key = (from_unit.lower(), to_unit.lower())
    return qty * conversions.get(key, 1)
