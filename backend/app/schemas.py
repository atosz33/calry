from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import Gender, MealType


class UserBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    gender: Gender
    weight_kg: float = Field(gt=0)
    height_cm: float = Field(gt=0)
    age: int | None = Field(default=None, ge=1, le=120)
    daily_calorie_goal: int | None = Field(default=None, ge=1, le=10000)


class RegisterRequest(UserBase):
    password: str = Field(min_length=8, max_length=255)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserUpdate(UserBase):
    pass


class UserRead(UserBase):
    id: int
    is_admin: bool
    created_at: datetime
    daily_calorie_target: int
    estimated_daily_calories: int

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    token: str
    user: UserRead


class LoginAuditRead(BaseModel):
    id: int
    email: str
    ip_address: str
    outcome: str
    reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserRead(UserRead):
    ingredient_count: int
    recipe_count: int
    meal_entry_count: int


class AdminRecipeRead(BaseModel):
    id: int
    user_id: int | None
    user_email: str | None
    name: str
    total_yield_grams: float
    total_calories: float
    calories_per_100g: float
    ingredient_count: int
    created_at: datetime


class IngredientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    calories_per_100g: float = Field(ge=0)


class IngredientUpdate(IngredientCreate):
    pass


class IngredientRead(IngredientCreate):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminIngredientCreate(IngredientCreate):
    user_id: int


class AdminIngredientRead(IngredientRead):
    user_id: int | None
    user_email: str | None


class RecipeIngredientCreate(BaseModel):
    ingredient_id: int
    amount_grams: float = Field(gt=0)


class RecipeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    ingredients: list[RecipeIngredientCreate] = Field(min_length=1)


class RecipeUpdate(RecipeCreate):
    pass


class RecipeIngredientRead(BaseModel):
    id: int
    ingredient_id: int
    ingredient_name: str
    amount_grams: float
    calories: float


class RecipeRead(BaseModel):
    id: int
    name: str
    total_yield_grams: float
    total_calories: float
    calories_per_100g: float
    ingredients: list[RecipeIngredientRead]
    created_at: datetime


class MealEntryCreate(BaseModel):
    recipe_id: int
    meal_type: MealType
    date: date
    grams_eaten: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=255)


class MealEntryUpdate(MealEntryCreate):
    pass


class MealEntryRead(BaseModel):
    id: int
    user_id: int
    recipe_id: int
    recipe_name: str
    meal_type: MealType
    date: date
    grams_eaten: float
    calories: float
    note: str | None
    created_at: datetime


class AdminMealEntryRead(MealEntryRead):
    user_email: str | None


class MealGroupRead(BaseModel):
    meal_type: MealType
    total_calories: float
    entries: list[MealEntryRead]


class DailySummaryRead(BaseModel):
    date: date
    user_id: int
    calorie_target: int
    consumed_calories: float
    remaining_calories: float
    meals: list[MealGroupRead]


class DeficitDayRead(BaseModel):
    date: date
    consumed_calories: float
    calorie_target: int
    deficit: float


class DeficitReportRead(BaseModel):
    days: int
    total_consumed_calories: float
    total_target_calories: float
    total_deficit: float
    average_daily_deficit: float
    entries: list[DeficitDayRead]
