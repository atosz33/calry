from collections import defaultdict

from .models import Gender, MealEntry, MealType, Recipe, User
from .schemas import (
    DailySummaryRead,
    DeficitDayRead,
    DeficitReportRead,
    MealEntryRead,
    MealGroupRead,
    RecipeIngredientRead,
    RecipeRead,
)


def estimate_daily_calories(user: User) -> int:
    if user.age:
        base = 10 * user.weight_kg + 6.25 * user.height_cm - 5 * user.age
        base += 5 if user.gender == Gender.male else -161
    else:
        gender_offset = 180 if user.gender == Gender.male else -80
        base = 9.5 * user.weight_kg + 4.8 * user.height_cm + gender_offset

    return max(1200, int(round(base)))


def resolve_daily_calorie_target(user: User) -> int:
    if user.daily_calorie_goal:
        return user.daily_calorie_goal
    return estimate_daily_calories(user)


def recipe_total_yield_grams(recipe: Recipe) -> float:
    return round(sum(item.amount_grams for item in recipe.ingredients), 2)


def recipe_total_calories(recipe: Recipe) -> float:
    return round(
        sum(item.amount_grams * item.ingredient.calories_per_100g / 100 for item in recipe.ingredients),
        2,
    )


def recipe_calories_per_100g(recipe: Recipe) -> float:
    total_yield = recipe_total_yield_grams(recipe)
    if total_yield == 0:
        return 0.0
    return round(recipe_total_calories(recipe) / total_yield * 100, 2)


def serialize_recipe(recipe: Recipe) -> RecipeRead:
    ingredients = [
        RecipeIngredientRead(
            id=item.id,
            ingredient_id=item.ingredient_id,
            ingredient_name=item.ingredient.name,
            amount_grams=item.amount_grams,
            calories=round(item.amount_grams * item.ingredient.calories_per_100g / 100, 2),
        )
        for item in recipe.ingredients
    ]

    return RecipeRead(
        id=recipe.id,
        name=recipe.name,
        total_yield_grams=recipe_total_yield_grams(recipe),
        total_calories=recipe_total_calories(recipe),
        calories_per_100g=recipe_calories_per_100g(recipe),
        ingredients=ingredients,
        created_at=recipe.created_at,
    )


def meal_entry_calories(entry: MealEntry) -> float:
    per_100g = recipe_calories_per_100g(entry.recipe)
    return round(entry.grams_eaten * per_100g / 100, 2)


def serialize_meal_entry(entry: MealEntry) -> MealEntryRead:
    return MealEntryRead(
        id=entry.id,
        user_id=entry.user_id,
        recipe_id=entry.recipe_id,
        recipe_name=entry.recipe.name,
        meal_type=entry.meal_type,
        date=entry.date,
        grams_eaten=entry.grams_eaten,
        calories=meal_entry_calories(entry),
        note=entry.note,
        created_at=entry.created_at,
    )


def build_daily_summary(user: User, entries: list[MealEntry], entry_date) -> DailySummaryRead:
    grouped: dict[MealType, list[MealEntryRead]] = defaultdict(list)
    for entry in entries:
        grouped[entry.meal_type].append(serialize_meal_entry(entry))

    meals = []
    for meal_type in MealType:
        meal_entries = grouped.get(meal_type, [])
        if not meal_entries:
            continue
        meals.append(
            MealGroupRead(
                meal_type=meal_type,
                total_calories=round(sum(item.calories for item in meal_entries), 2),
                entries=meal_entries,
            )
        )

    consumed = round(sum(group.total_calories for group in meals), 2)
    target = resolve_daily_calorie_target(user)

    return DailySummaryRead(
        date=entry_date,
        user_id=user.id,
        calorie_target=target,
        consumed_calories=consumed,
        remaining_calories=round(target - consumed, 2),
        meals=meals,
    )


def build_deficit_report(user: User, entries: list[MealEntry], start_date, end_date) -> DeficitReportRead:
    entries_by_date: dict = defaultdict(list)
    for entry in entries:
        entries_by_date[entry.date].append(entry)

    target = resolve_daily_calorie_target(user)
    breakdown = []
    current_date = start_date

    while current_date <= end_date:
        day_entries = entries_by_date.get(current_date, [])
        consumed = round(sum(meal_entry_calories(entry) for entry in day_entries), 2)
        deficit = round(target - consumed, 2)
        breakdown.append(
            DeficitDayRead(
                date=current_date,
                consumed_calories=consumed,
                calorie_target=target,
                deficit=deficit,
            )
        )
        current_date = current_date.fromordinal(current_date.toordinal() + 1)

    total_consumed = round(sum(item.consumed_calories for item in breakdown), 2)
    total_target = round(sum(item.calorie_target for item in breakdown), 2)
    total_deficit = round(sum(item.deficit for item in breakdown), 2)
    measured_days = len(breakdown)

    return DeficitReportRead(
        days=measured_days,
        total_consumed_calories=total_consumed,
        total_target_calories=total_target,
        total_deficit=total_deficit,
        average_daily_deficit=round(total_deficit / measured_days, 2) if measured_days else 0,
        entries=breakdown,
    )
