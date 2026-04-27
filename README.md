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
- Manage ingredients with calories per 100 grams
- Build recipes from ingredient quantities and automatic total weight calculation
- Log recipe portions into daily meals
- Edit and delete ingredients, recipes, and meal entries
- See consumed, remaining, and grouped daily calories

## Data Model

- `User`: authenticated account with profile data
- `Ingredient`: base ingredient with calories per 100g
- `Recipe`: reusable recipe composed of ingredients
- `MealEntry`: eaten grams of a recipe on a given date and meal type

## Notes

- Macro tracking is intentionally left out for now, but the schema is structured so it can be added later.
- `age` is optional. If provided, daily calorie estimation uses Mifflin-St Jeor. Otherwise a simpler weight/height-based estimate is used.
- If you already ran an older local version, legacy SQLite columns are handled for compatibility, but old anonymous users are not converted into email/password accounts automatically.
