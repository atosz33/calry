# Calry

Full-stack calorie tracking app with a FastAPI backend and React frontend.

## Stack

- Backend: Python, FastAPI, SQLAlchemy, SQLite
- Frontend: React, Vite
- Containers: Docker Compose

## Run

```bash
docker compose up --build
```

The app will be available on:

- Frontend: `http://localhost:8081`
- Backend API docs: `http://localhost:5001/docs`

## Main Features

- Register and log in with email and password
- Update your own profile data and calorie target estimation
- Manage ingredients with calories and macros per 100 grams
- Build recipes from ingredient quantities with automatic total weight, calorie, protein, carbohydrate, and fat calculation
- Log recipe portions into daily meals
- Edit and delete ingredients, recipes, and meal entries
- See consumed, remaining, grouped daily calories, and consumed macros
- Optional per-user AI mode for Gemini-powered ingredient nutrition and recipe suggestions

## Data Model

- `User`: authenticated account with profile data
- `Ingredient`: base ingredient with calories, protein, carbohydrates, and fat per 100g
- `Recipe`: reusable recipe composed of ingredients, with calculated nutrition totals
- `MealEntry`: eaten grams of a recipe on a given date and meal type, with calculated nutrition values

## Notes

- `age` is optional. If provided, daily calorie estimation uses Mifflin-St Jeor. Otherwise a simpler weight/height-based estimate is used.
- AI mode is disabled by default per user. Set `GEMINI_API_KEY` for the backend container, and optionally `GEMINI_MODEL` (defaults to `gemini-3.1-flash-preview`).
- If you already ran an older local version, legacy SQLite columns are handled for compatibility, but old anonymous users are not converted into email/password accounts automatically.

## Local Admin User

Create a normal account in the UI first, then promote that account locally.

With Docker Compose:

```bash
docker compose exec backend python -m app.make_admin user@example.com
```

Without Docker, from the `backend` directory:

```bash
python -m app.make_admin user@example.com
```

After the command succeeds, log out and log back in with that user. The Admin button appears in the footer. In the Admin / Users view, admins can also toggle `AI integration` per user. That toggle updates the user's `ai_enabled` flag through:

```http
PATCH /admin/users/{user_id}
```

Request body:

```json
{
  "ai_enabled": true
}
```

## AI Integration

AI integration is per user and is off by default. It works only when both conditions are true:

- the backend has `GEMINI_API_KEY` configured
- the current user's `ai_enabled` flag is `true`

For local Docker Compose, set the key before starting the app:

```bash
GEMINI_API_KEY="your-key" docker compose up --build
```

Optional model override:

```bash
GEMINI_MODEL="gemini-3.1-flash-preview"
```

The backend checks the current authenticated user before every AI request. If `ai_enabled` is false, the API returns `403`.

### AI Status

```http
GET /ai/status
```

Response:

```json
{
  "enabled": true,
  "configured": true
}
```

`enabled` means the logged-in user has AI mode enabled. `configured` means the backend has a Gemini API key.

### Ingredient Nutrition Suggestion

```http
POST /ai/ingredient-nutrition
```

Request model:

```json
{
  "name": "chicken breast"
}
```

Response model:

```json
{
  "name": "chicken breast",
  "calories_per_100g": 165,
  "protein_per_100g": 31,
  "carbs_per_100g": 0,
  "fat_per_100g": 3.6,
  "note": "Common raw/plain form."
}
```

UI flow:

- The user types an ingredient name in the ingredient form.
- The AI button sends `{ "name": ingredientForm.name }`.
- The response fills `calories_per_100g`, `protein_per_100g`, `carbs_per_100g`, and `fat_per_100g` in the form.
- Nothing is stored yet. The ingredient is saved only when the user submits the normal ingredient form, which calls `POST /ingredients` or `PUT /ingredients/{id}`.

### Recipe Suggestions

```http
POST /ai/recipe-suggestions
```

Request model:

```json
{
  "only_existing_ingredients": true,
  "prompt": "high protein dinner"
}
```

Response model:

```json
[
  {
    "name": "Chicken Rice Bowl",
    "instructions": "Cook rice, grill chicken, combine with vegetables.",
    "ingredients": [
      {
        "ingredient_id": 1,
        "ingredient_name": "chicken breast",
        "amount_grams": 180
      },
      {
        "ingredient_id": 2,
        "ingredient_name": "rice",
        "amount_grams": 120
      }
    ]
  }
]
```

UI flow:

- The user sets `only_existing_ingredients` and an optional prompt.
- The UI sends those fields to `/ai/recipe-suggestions`.
- The backend sends available ingredients and the prompt to Gemini, then normalizes the JSON response.
- Suggestions are shown as temporary recipe cards.
- Clicking `Use recipe` copies the suggestion into the recipe form.
- Nothing is stored yet. The recipe is saved only when the user submits the normal recipe form, which calls `POST /recipes` or `PUT /recipes/{id}`.

When `only_existing_ingredients` is true, the backend tries to return suggestions with existing `ingredient_id` values. The UI only copies suggestion ingredients that have an `ingredient_id`, because saved recipes must reference stored ingredients.
