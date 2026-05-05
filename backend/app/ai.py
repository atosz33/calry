import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from fastapi import HTTPException

from .models import Ingredient


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def gemini_is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def suggest_ingredient_nutrition(name: str) -> dict[str, Any]:
    prompt = f"""
Estimate common nutrition values per 100 grams for this ingredient: {name}.
Return only JSON with these keys:
name, calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, note.
Use grams for macros, kcal for calories. If the ingredient is ambiguous, choose the most common raw/plain form and mention that in note.
"""
    data = _generate_json(prompt)
    return {
        "name": str(data.get("name") or name),
        "calories_per_100g": _non_negative_number(data.get("calories_per_100g")),
        "protein_per_100g": _non_negative_number(data.get("protein_per_100g")),
        "carbs_per_100g": _non_negative_number(data.get("carbs_per_100g")),
        "fat_per_100g": _non_negative_number(data.get("fat_per_100g")),
        "note": data.get("note") if isinstance(data.get("note"), str) else None,
    }


def suggest_recipes(
    ingredients: list[Ingredient],
    only_existing_ingredients: bool,
    prompt: str | None,
) -> list[dict[str, Any]]:
    ingredient_lines = "\n".join(
        f"- id={ingredient.id}; name={ingredient.name}; kcal={ingredient.calories_per_100g}; "
        f"protein={ingredient.protein_per_100g}; carbs={ingredient.carbs_per_100g}; fat={ingredient.fat_per_100g}"
        for ingredient in ingredients
    )
    mode = (
        "Use only ingredients from the list. Each returned ingredient must include the matching ingredient_id."
        if only_existing_ingredients
        else "Prefer ingredients from the list, but you may add new common ingredients with ingredient_id null."
    )
    extra_prompt = prompt or "No extra preference."
    request_prompt = f"""
Create 3 practical recipe ideas for a calorie tracking app.
{mode}
Available ingredients:
{ingredient_lines or "- none"}
User preference: {extra_prompt}

Return only JSON with this shape:
{{
  "recipes": [
    {{
      "name": "Recipe name",
      "instructions": "Short preparation steps.",
      "ingredients": [
        {{"ingredient_id": 1, "ingredient_name": "Exact ingredient name", "amount_grams": 100}}
      ]
    }}
  ]
}}
"""
    data = _generate_json(request_prompt)
    raw_recipes = data.get("recipes") if isinstance(data, dict) else None
    if not isinstance(raw_recipes, list):
        raise HTTPException(status_code=502, detail="AI returned an invalid recipe response")

    ingredient_by_id = {ingredient.id: ingredient for ingredient in ingredients}
    normalized_recipes = []
    for raw_recipe in raw_recipes[:3]:
        if not isinstance(raw_recipe, dict):
            continue
        raw_ingredients = raw_recipe.get("ingredients")
        if not isinstance(raw_ingredients, list):
            continue
        normalized_ingredients = []
        for raw_item in raw_ingredients:
            if not isinstance(raw_item, dict):
                continue
            ingredient_id = raw_item.get("ingredient_id")
            if isinstance(ingredient_id, str) and ingredient_id.isdigit():
                ingredient_id = int(ingredient_id)
            if not isinstance(ingredient_id, int) or ingredient_id not in ingredient_by_id:
                ingredient_id = None
            if only_existing_ingredients and ingredient_id is None:
                continue
            ingredient_name = (
                ingredient_by_id[ingredient_id].name
                if ingredient_id is not None
                else str(raw_item.get("ingredient_name") or "").strip()
            )
            amount = _positive_number(raw_item.get("amount_grams"))
            if not ingredient_name or amount <= 0:
                continue
            normalized_ingredients.append(
                {
                    "ingredient_id": ingredient_id,
                    "ingredient_name": ingredient_name,
                    "amount_grams": amount,
                }
            )
        if normalized_ingredients:
            normalized_recipes.append(
                {
                    "name": str(raw_recipe.get("name") or "AI recipe")[:120],
                    "instructions": raw_recipe.get("instructions")
                    if isinstance(raw_recipe.get("instructions"), str)
                    else None,
                    "ingredients": normalized_ingredients,
                }
            )

    if not normalized_recipes:
        raise HTTPException(status_code=502, detail="AI did not return usable recipes")
    return normalized_recipes


def _generate_json(prompt: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Gemini API key is not configured")

    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-preview")
    request = urllib.request.Request(
        GEMINI_API_URL.format(model=model),
        data=json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode() or str(error)
        raise HTTPException(status_code=502, detail=f"Gemini API error: {detail[:500]}")
    except (urllib.error.URLError, TimeoutError) as error:
        raise HTTPException(status_code=502, detail=f"Gemini API is unavailable: {error}")

    text = _extract_text(payload)
    try:
        parsed = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI returned non-JSON content")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="AI returned an invalid JSON shape")
    return parsed


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise HTTPException(status_code=502, detail="AI returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not isinstance(parts, list):
        raise HTTPException(status_code=502, detail="AI returned no content")
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text.strip():
        raise HTTPException(status_code=502, detail="AI returned empty content")
    return text


def _strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return match.group(1) if match else text.strip()


def _non_negative_number(value: Any) -> float:
    try:
        return round(max(0.0, float(value)), 2)
    except (TypeError, ValueError):
        return 0.0


def _positive_number(value: Any) -> float:
    try:
        return round(max(0.0, float(value)), 2)
    except (TypeError, ValueError):
        return 0.0
