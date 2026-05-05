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
