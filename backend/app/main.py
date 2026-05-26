import os
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .database import get_db, init_db
from .ai import (
    AI_DISABLED_CODE,
    AI_GENERAL_ERROR_CODE,
    ai_error,
    gemini_is_configured,
    suggest_ingredient_nutrition,
    suggest_recipes,
)
from .models import (
    AiUsageLog,
    Ingredient,
    InventoryItem,
    LoginAudit,
    MealEntry,
    Recipe,
    RecipeIngredient,
    ShoppingListItem,
    User,
)
from .schemas import (
    AuthResponse,
    AdminIngredientRead,
    AdminMealEntryRead,
    AdminRecipeRead,
    AdminUserRead,
    AdminUserUpdate,
    DailySummaryRead,
    DeficitReportRead,
    IngredientCreate,
    IngredientNutritionSuggestionRead,
    IngredientNutritionSuggestionRequest,
    InventoryItemCreate,
    InventoryItemRead,
    LoginAuditRead,
    IngredientRead,
    IngredientUpdate,
    LoginRequest,
    MealEntryCreate,
    MealEntryRead,
    MealEntryUpdate,
    RecipeUpdate,
    RegisterRequest,
    RecipeSuggestionRead,
    RecipeSuggestionRequest,
    RecipePrepareRequest,
    RecipeCreate,
    RecipeRead,
    ShoppingListItemCreate,
    ShoppingListPurchaseRead,
    ShoppingListPurchaseRequest,
    ShoppingListItemRead,
    UserRead,
    UserUpdate,
)
from .security import hash_password, issue_auth_token, verify_password
from .security import (
    ACCOUNT_LOCK_MINUTES,
    MAX_FAILED_LOGINS_PER_ACCOUNT,
    clear_failed_ip_attempts,
    is_ip_banned,
    register_failed_ip_attempt,
    utc_now,
)
from .services import (
    build_daily_summary,
    build_deficit_report,
    estimate_daily_calories,
    recipe_total_yield_grams,
    resolve_daily_calorie_target,
    serialize_meal_entry,
    serialize_recipe,
)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def get_cors_origins() -> list[str]:
    raw_origins = os.getenv("CORS_ORIGINS", "")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or DEFAULT_CORS_ORIGINS


init_db()

app = FastAPI(title="Calry API", version="0.1.0")
security = HTTPBearer(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    field_path = ".".join(str(part) for part in first_error.get("loc", []) if part != "body")
    field_label = field_path or "request"
    message = f"Invalid value for {field_label}."
    public_errors = [
        {key: value for key, value in error.items() if key != "input"}
        for error in errors
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": message,
                "errors": jsonable_encoder(public_errors),
            }
        },
    )


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


def serialize_user(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=bool(user.is_admin),
        ai_enabled=bool(user.ai_enabled),
        gender=user.gender,
        weight_kg=user.weight_kg,
        height_cm=user.height_cm,
        age=user.age,
        daily_calorie_goal=user.daily_calorie_goal,
        created_at=user.created_at,
        daily_calorie_target=resolve_daily_calorie_target(user),
        estimated_daily_calories=estimate_daily_calories(user),
    )


def create_login_audit(
    db: Session,
    email: str,
    ip_address: str,
    outcome: str,
    reason: str | None = None,
    user_id: int | None = None,
) -> None:
    db.add(
        LoginAudit(
            user_id=user_id,
            email=email,
            ip_address=ip_address,
            outcome=outcome,
            reason=reason,
        )
    )
    db.commit()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    user = db.scalar(select(User).where(User.auth_token == credentials.credentials))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def get_owned_recipe(recipe_id: int, current_user: User, db: Session) -> Recipe:
    recipe = (
        db.execute(
            select(Recipe)
            .where(Recipe.id == recipe_id, Recipe.user_id == current_user.id)
            .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        )
        .scalars()
        .unique()
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


def get_ingredient(ingredient_id: int, db: Session) -> Ingredient:
    ingredient = db.get(Ingredient, ingredient_id)
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return ingredient


def get_owned_inventory_item(item_id: int, current_user: User, db: Session) -> InventoryItem:
    item = db.scalar(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.user_id == current_user.id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item


def get_owned_shopping_item(item_id: int, current_user: User, db: Session) -> ShoppingListItem:
    item = db.scalar(
        select(ShoppingListItem).where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.user_id == current_user.id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Shopping list item not found")
    return item


def get_owned_meal_entry(meal_entry_id: int, current_user: User, db: Session) -> MealEntry:
    entry = (
        db.execute(
            select(MealEntry)
            .where(MealEntry.id == meal_entry_id, MealEntry.user_id == current_user.id)
            .options(joinedload(MealEntry.recipe).joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        )
        .scalars()
        .unique()
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Meal entry not found")
    return entry


def ensure_ai_enabled(current_user: User) -> None:
    if not current_user.ai_enabled:
        raise ai_error(403, AI_DISABLED_CODE, "AI mode is disabled for this user.")


def extract_error_code(error: HTTPException) -> str:
    if isinstance(error.detail, dict):
        code = error.detail.get("code")
        if isinstance(code, str):
            return code
    return AI_GENERAL_ERROR_CODE


def create_ai_usage_log(
    db: Session,
    current_user: User,
    request_type: str,
    outcome: str,
    error_code: str | None = None,
) -> None:
    db.add(
        AiUsageLog(
            user_id=current_user.id,
            request_type=request_type,
            outcome=outcome,
            error_code=error_code,
        )
    )
    db.commit()


def get_ai_usage_counts(db: Session) -> dict[int, dict[str, int]]:
    rows = db.execute(
        select(AiUsageLog.user_id, AiUsageLog.request_type, func.count(AiUsageLog.id))
        .group_by(AiUsageLog.user_id, AiUsageLog.request_type)
    ).all()
    counts: dict[int, dict[str, int]] = {}
    for user_id, request_type, count in rows:
        counts.setdefault(user_id, {})[request_type] = count
    return counts


def resolve_inventory_payload(
    payload: InventoryItemCreate,
    db: Session,
) -> tuple[int | None, str, float | None]:
    ingredient_id = payload.ingredient_id
    if ingredient_id is not None:
        ingredient = get_ingredient(ingredient_id, db)
        return ingredient.id, ingredient.name, payload.amount_grams

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    return None, name, payload.amount_grams


def normalize_optional_text(value: str | None) -> str:
    if value is None:
        return ""
    stripped = value.strip()
    return stripped


def ingredient_duplicate_query(name: str, brand: str, ingredient_id: int | None = None):
    conditions = [Ingredient.name.ilike(name.strip())]
    conditions.append(Ingredient.brand.ilike(brand))
    if ingredient_id is not None:
        conditions.append(Ingredient.id != ingredient_id)
    return select(Ingredient).where(*conditions)


def add_inventory_item(
    current_user: User,
    ingredient_id: int | None,
    name: str,
    amount_grams: float | None,
    db: Session,
) -> InventoryItem:
    existing = None
    if ingredient_id is not None:
        existing = db.scalar(
            select(InventoryItem).where(
                InventoryItem.user_id == current_user.id,
                InventoryItem.ingredient_id == ingredient_id,
            )
        )

    if existing:
        if existing.amount_grams is None or amount_grams is None:
            existing.amount_grams = None
        else:
            existing.amount_grams = round(existing.amount_grams + amount_grams, 2)
        db.add(existing)
        return existing

    item = InventoryItem(
        user_id=current_user.id,
        ingredient_id=ingredient_id,
        name=name.strip(),
        amount_grams=amount_grams,
    )
    db.add(item)
    return item


def resolve_purchase_ingredient(
    payload: ShoppingListPurchaseRequest,
    db: Session,
    current_user: User,
) -> Ingredient | None:
    if payload.ingredient_id is not None and payload.ingredient is not None:
        raise HTTPException(status_code=400, detail="Choose either ingredient_id or ingredient")

    if payload.ingredient_id is not None:
        return get_ingredient(payload.ingredient_id, db)

    if payload.ingredient is None:
        return None

    ingredient_payload = payload.ingredient
    brand = normalize_optional_text(ingredient_payload.brand)
    existing = db.scalar(ingredient_duplicate_query(ingredient_payload.name, brand))
    if existing:
        return existing

    ingredient = Ingredient(
        **{
            **ingredient_payload.model_dump(exclude={"brand", "name"}),
            "name": ingredient_payload.name.strip(),
            "brand": brand,
        },
        user_id=current_user.id,
    )
    db.add(ingredient)
    db.flush()
    return ingredient


def inventory_items_query(current_user: User):
    return (
        select(InventoryItem)
        .where(InventoryItem.user_id == current_user.id)
        .order_by(InventoryItem.created_at.desc())
    )


@app.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.scalar(select(User).where(User.email.ilike(payload.email)))
    if existing:
        raise HTTPException(status_code=400, detail="Email is already registered")

    token = issue_auth_token()
    user = User(
        name=payload.name,
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        auth_token=token,
        gender=payload.gender,
        weight_kg=payload.weight_kg,
        height_cm=payload.height_cm,
        age=payload.age,
        daily_calorie_goal=payload.daily_calorie_goal,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return AuthResponse(token=token, user=serialize_user(user))


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> AuthResponse:
    normalized_email = payload.email.strip().lower()
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    client_ip = client_ip.split(",")[0].strip()

    if is_ip_banned(client_ip):
        create_login_audit(
            db,
            email=normalized_email,
            ip_address=client_ip,
            outcome="blocked",
            reason="ip_banned",
        )
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Try again later.")

    user = db.scalar(select(User).where(User.email == normalized_email))
    now = utc_now()

    if user and user.locked_until and user.locked_until > now:
        create_login_audit(
            db,
            email=normalized_email,
            ip_address=client_ip,
            outcome="blocked",
            reason="account_locked",
            user_id=user.id,
        )
        raise HTTPException(status_code=423, detail="Account temporarily locked. Try again later.")

    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        register_failed_ip_attempt(client_ip)
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_LOGINS_PER_ACCOUNT:
                user.locked_until = now + timedelta(minutes=ACCOUNT_LOCK_MINUTES)
                user.failed_login_attempts = 0
            db.add(user)
            db.commit()
        create_login_audit(
            db,
            email=normalized_email,
            ip_address=client_ip,
            outcome="failed",
            reason="invalid_credentials",
            user_id=user.id if user else None,
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    clear_failed_ip_attempts(client_ip)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.auth_token = issue_auth_token()
    db.add(user)
    db.commit()
    create_login_audit(
        db,
        email=normalized_email,
        ip_address=client_ip,
        outcome="success",
        reason=None,
        user_id=user.id,
    )
    db.refresh(user)
    return AuthResponse(token=user.auth_token, user=serialize_user(user))


@app.get("/auth/audit-logs", response_model=list[LoginAuditRead])
def get_auth_audit_logs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[LoginAudit]:
    return db.scalars(
        select(LoginAudit)
        .where(LoginAudit.user_id == current_user.id)
        .order_by(LoginAudit.created_at.desc())
        .limit(limit)
    ).all()


@app.get("/auth/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return serialize_user(current_user)


@app.put("/auth/me", response_model=UserRead)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserRead:
    email_owner = db.scalar(select(User).where(User.email.ilike(payload.email), User.id != current_user.id))
    if email_owner:
        raise HTTPException(status_code=400, detail="Email is already registered")

    for field, value in payload.model_dump().items():
        setattr(current_user, field, value if field != "email" else value.strip().lower())

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return serialize_user(current_user)


@app.get("/admin/users", response_model=list[AdminUserRead])
def admin_list_users(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> list[AdminUserRead]:
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    ingredient_counts = dict(
        db.execute(select(Ingredient.user_id, func.count(Ingredient.id)).group_by(Ingredient.user_id)).all()
    )
    recipe_counts = dict(
        db.execute(select(Recipe.user_id, func.count(Recipe.id)).group_by(Recipe.user_id)).all()
    )
    meal_counts = dict(
        db.execute(select(MealEntry.user_id, func.count(MealEntry.id)).group_by(MealEntry.user_id)).all()
    )
    ai_usage_counts = get_ai_usage_counts(db)

    return [
        AdminUserRead(
            **serialize_user(user).model_dump(),
            ingredient_count=ingredient_counts.get(user.id, 0),
            recipe_count=recipe_counts.get(user.id, 0),
            meal_entry_count=meal_counts.get(user.id, 0),
            ai_ingredient_call_count=ai_usage_counts.get(user.id, {}).get("ingredient", 0),
            ai_recipe_call_count=ai_usage_counts.get(user.id, {}).get("recipe", 0),
        )
        for user in users
    ]


@app.patch("/admin/users/{user_id}", response_model=AdminUserRead)
def admin_update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> AdminUserRead:
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_user.ai_enabled = payload.ai_enabled
    db.add(target_user)
    db.commit()
    db.refresh(target_user)

    ingredient_count = db.scalar(select(func.count(Ingredient.id)).where(Ingredient.user_id == target_user.id)) or 0
    recipe_count = db.scalar(select(func.count(Recipe.id)).where(Recipe.user_id == target_user.id)) or 0
    meal_entry_count = db.scalar(select(func.count(MealEntry.id)).where(MealEntry.user_id == target_user.id)) or 0
    ai_ingredient_call_count = (
        db.scalar(
            select(func.count(AiUsageLog.id)).where(
                AiUsageLog.user_id == target_user.id,
                AiUsageLog.request_type == "ingredient",
            )
        )
        or 0
    )
    ai_recipe_call_count = (
        db.scalar(
            select(func.count(AiUsageLog.id)).where(
                AiUsageLog.user_id == target_user.id,
                AiUsageLog.request_type == "recipe",
            )
        )
        or 0
    )

    return AdminUserRead(
        **serialize_user(target_user).model_dump(),
        ingredient_count=ingredient_count,
        recipe_count=recipe_count,
        meal_entry_count=meal_entry_count,
        ai_ingredient_call_count=ai_ingredient_call_count,
        ai_recipe_call_count=ai_recipe_call_count,
    )


@app.get("/admin/ingredients", response_model=list[AdminIngredientRead])
def admin_list_ingredients(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> list[AdminIngredientRead]:
    rows = db.execute(
        select(Ingredient, User.email)
        .outerjoin(User, Ingredient.user_id == User.id)
        .order_by(Ingredient.created_at.desc())
    ).all()
    return [
        AdminIngredientRead(
            id=ingredient.id,
            user_id=ingredient.user_id,
            user_email=email,
            name=ingredient.name,
            brand=ingredient.brand,
            calories_per_100g=ingredient.calories_per_100g,
            protein_per_100g=ingredient.protein_per_100g,
            carbs_per_100g=ingredient.carbs_per_100g,
            fat_per_100g=ingredient.fat_per_100g,
            created_at=ingredient.created_at,
        )
        for ingredient, email in rows
    ]


@app.post("/admin/ingredients", response_model=AdminIngredientRead, status_code=201)
def admin_create_ingredient(
    payload: IngredientCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> AdminIngredientRead:
    brand = normalize_optional_text(payload.brand)
    duplicate = db.scalar(ingredient_duplicate_query(payload.name, brand))
    if duplicate:
        raise HTTPException(status_code=400, detail="Ingredient already exists")

    ingredient = Ingredient(
        user_id=current_admin.id,
        name=payload.name.strip(),
        brand=brand,
        calories_per_100g=payload.calories_per_100g,
        protein_per_100g=payload.protein_per_100g,
        carbs_per_100g=payload.carbs_per_100g,
        fat_per_100g=payload.fat_per_100g,
    )
    db.add(ingredient)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ingredient already exists")
    db.refresh(ingredient)
    return AdminIngredientRead(
        id=ingredient.id,
        user_id=ingredient.user_id,
        user_email=current_admin.email,
        name=ingredient.name,
        brand=ingredient.brand,
        calories_per_100g=ingredient.calories_per_100g,
        protein_per_100g=ingredient.protein_per_100g,
        carbs_per_100g=ingredient.carbs_per_100g,
        fat_per_100g=ingredient.fat_per_100g,
        created_at=ingredient.created_at,
    )


@app.get("/admin/recipes", response_model=list[AdminRecipeRead])
def admin_list_recipes(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> list[AdminRecipeRead]:
    rows = db.execute(
        select(Recipe, User.email)
        .outerjoin(User, Recipe.user_id == User.id)
        .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .order_by(Recipe.created_at.desc())
    ).unique().all()
    items = []
    for recipe, email in rows:
        serialized = serialize_recipe(recipe)
        items.append(
            AdminRecipeRead(
                id=recipe.id,
                user_id=recipe.user_id,
                user_email=email,
                name=recipe.name,
                prep_time_minutes=recipe.prep_time_minutes,
                total_yield_grams=recipe.total_yield_grams,
                total_calories=serialized.total_calories,
                calories_per_100g=serialized.calories_per_100g,
                total_protein=serialized.total_protein,
                protein_per_100g=serialized.protein_per_100g,
                total_carbs=serialized.total_carbs,
                carbs_per_100g=serialized.carbs_per_100g,
                total_fat=serialized.total_fat,
                fat_per_100g=serialized.fat_per_100g,
                ingredient_count=len(recipe.ingredients),
                created_at=recipe.created_at,
            )
        )
    return items


@app.get("/admin/meal-entries", response_model=list[AdminMealEntryRead])
def admin_list_meal_entries(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
) -> list[AdminMealEntryRead]:
    rows = db.execute(
        select(MealEntry, User.email)
        .join(User, MealEntry.user_id == User.id)
        .options(joinedload(MealEntry.recipe).joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .order_by(MealEntry.created_at.desc())
        .limit(limit)
    ).unique().all()
    return [
        AdminMealEntryRead(**serialize_meal_entry(entry).model_dump(), user_email=email)
        for entry, email in rows
    ]


@app.get("/users/me/dashboard", response_model=DailySummaryRead)
def get_dashboard(
    target_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailySummaryRead:
    entries = db.scalars(
        select(MealEntry)
        .where(MealEntry.user_id == current_user.id, MealEntry.date == target_date)
        .options(joinedload(MealEntry.recipe).joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .order_by(MealEntry.created_at.asc())
    ).unique().all()

    return build_daily_summary(current_user, entries, target_date)


@app.get("/ai/status")
def get_ai_status(current_user: User = Depends(get_current_user)) -> dict[str, bool]:
    return {
        "enabled": bool(current_user.ai_enabled),
        "configured": gemini_is_configured(),
    }


@app.post("/ai/ingredient-nutrition", response_model=IngredientNutritionSuggestionRead)
def suggest_ingredient_nutrition_endpoint(
    payload: IngredientNutritionSuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IngredientNutritionSuggestionRead:
    ensure_ai_enabled(current_user)
    try:
        suggestion = IngredientNutritionSuggestionRead(
            **suggest_ingredient_nutrition(payload.name, payload.language)
        )
    except HTTPException as error:
        create_ai_usage_log(db, current_user, "ingredient", "failed", extract_error_code(error))
        raise

    create_ai_usage_log(db, current_user, "ingredient", "success")
    return suggestion


@app.post("/ai/recipe-suggestions", response_model=list[RecipeSuggestionRead])
def suggest_recipe_endpoint(
    payload: RecipeSuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RecipeSuggestionRead]:
    ensure_ai_enabled(current_user)
    inventory_items = db.scalars(
        select(InventoryItem)
        .where(InventoryItem.user_id == current_user.id)
        .order_by(InventoryItem.name.asc())
    ).all()
    ingredient_ids = [item.ingredient_id for item in inventory_items if item.ingredient_id is not None]
    ingredients = db.scalars(
        select(Ingredient)
        .where(Ingredient.id.in_(ingredient_ids))
        .order_by(Ingredient.name.asc())
    ).all() if ingredient_ids else []
    amount_by_ingredient_id = {
        item.ingredient_id: item.amount_grams
        for item in inventory_items
        if item.ingredient_id is not None
    }
    try:
        suggestions = suggest_recipes(
            ingredients=ingredients,
            available_amounts=amount_by_ingredient_id,
            only_existing_ingredients=payload.only_existing_ingredients,
            prompt=payload.prompt,
            language=payload.language,
        )
        response = [RecipeSuggestionRead(**suggestion) for suggestion in suggestions]
    except HTTPException as error:
        create_ai_usage_log(db, current_user, "recipe", "failed", extract_error_code(error))
        raise

    create_ai_usage_log(db, current_user, "recipe", "success")
    return response


@app.get("/inventory-items", response_model=list[InventoryItemRead])
def list_inventory_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[InventoryItem]:
    return db.scalars(inventory_items_query(current_user)).all()


@app.post("/inventory-items", response_model=InventoryItemRead, status_code=201)
def create_inventory_item(
    payload: InventoryItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InventoryItem:
    ingredient_id, name, amount_grams = resolve_inventory_payload(payload, db)
    item = add_inventory_item(current_user, ingredient_id, name, amount_grams, db)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/inventory-items/{item_id}", status_code=204)
def delete_inventory_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    item = get_owned_inventory_item(item_id, current_user, db)
    db.delete(item)
    db.commit()


@app.get("/shopping-list", response_model=list[ShoppingListItemRead])
def list_shopping_list(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ShoppingListItem]:
    return db.scalars(
        select(ShoppingListItem)
        .where(ShoppingListItem.user_id == current_user.id)
        .order_by(ShoppingListItem.is_purchased.asc(), ShoppingListItem.created_at.desc())
    ).all()


@app.post("/shopping-list", response_model=ShoppingListItemRead, status_code=201)
def create_shopping_list_item(
    payload: ShoppingListItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShoppingListItem:
    ingredient_id = payload.ingredient_id
    name = payload.name.strip()
    if ingredient_id is not None:
        ingredient = get_ingredient(ingredient_id, db)
        name = ingredient.name

    item = ShoppingListItem(
        user_id=current_user.id,
        ingredient_id=ingredient_id,
        name=name,
        amount_grams=payload.amount_grams,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.post("/shopping-list/{item_id}/purchase", response_model=ShoppingListPurchaseRead)
def purchase_shopping_list_item(
    item_id: int,
    payload: ShoppingListPurchaseRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShoppingListPurchaseRead:
    item = get_owned_shopping_item(item_id, current_user, db)
    purchase_payload = payload or ShoppingListPurchaseRequest()
    ingredient = resolve_purchase_ingredient(purchase_payload, db, current_user)
    ingredient_id = ingredient.id if ingredient else item.ingredient_id
    item_name = ingredient.name if ingredient else item.name
    amount_grams = (
        purchase_payload.amount_grams
        if "amount_grams" in purchase_payload.model_fields_set
        else item.amount_grams
    )
    inventory_item = add_inventory_item(current_user, ingredient_id, item_name, amount_grams, db)
    db.delete(item)
    db.commit()
    db.refresh(inventory_item)
    if ingredient:
        db.refresh(ingredient)
    return ShoppingListPurchaseRead(inventory_item=inventory_item, ingredient=ingredient)


@app.delete("/shopping-list/{item_id}", status_code=204)
def delete_shopping_list_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    item = get_owned_shopping_item(item_id, current_user, db)
    db.delete(item)
    db.commit()


@app.get("/reports/deficit", response_model=DeficitReportRead)
def get_deficit_report(
    days: int = Query(default=7, ge=1, le=365),
    end_date: date | None = Query(default=None, alias="end_date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeficitReportRead:
    report_end_date = end_date or date.today()
    requested_start_date = report_end_date - timedelta(days=days - 1)
    registration_date = current_user.created_at.date()
    effective_start_date = max(requested_start_date, registration_date)

    if effective_start_date > report_end_date:
        effective_start_date = report_end_date

    entries = db.scalars(
        select(MealEntry)
        .where(
            MealEntry.user_id == current_user.id,
            MealEntry.date >= effective_start_date,
            MealEntry.date <= report_end_date,
        )
        .options(joinedload(MealEntry.recipe).joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .order_by(MealEntry.date.asc(), MealEntry.created_at.asc())
    ).unique().all()

    return build_deficit_report(current_user, entries, effective_start_date, report_end_date)


@app.get("/ingredients", response_model=list[IngredientRead])
def list_ingredients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Ingredient]:
    return db.scalars(
        select(Ingredient)
        .order_by(Ingredient.name.asc())
    ).all()


@app.post("/ingredients", response_model=IngredientRead, status_code=201)
def create_ingredient(
    payload: IngredientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ingredient:
    brand = normalize_optional_text(payload.brand)
    existing = db.scalar(ingredient_duplicate_query(payload.name, brand))
    if existing:
        raise HTTPException(status_code=400, detail="Ingredient already exists")

    ingredient = Ingredient(
        **{
            **payload.model_dump(exclude={"brand", "name"}),
            "name": payload.name.strip(),
            "brand": brand,
        },
        user_id=current_user.id,
    )
    db.add(ingredient)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ingredient already exists")
    db.refresh(ingredient)
    return ingredient


@app.put("/ingredients/{ingredient_id}", response_model=IngredientRead)
def update_ingredient(
    ingredient_id: int,
    payload: IngredientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Ingredient:
    ingredient = get_ingredient(ingredient_id, db)
    brand = normalize_optional_text(payload.brand)
    duplicate = db.scalar(ingredient_duplicate_query(payload.name, brand, ingredient_id))
    if duplicate:
        raise HTTPException(status_code=400, detail="Ingredient already exists")

    ingredient.name = payload.name.strip()
    ingredient.brand = brand
    ingredient.calories_per_100g = payload.calories_per_100g
    ingredient.protein_per_100g = payload.protein_per_100g
    ingredient.carbs_per_100g = payload.carbs_per_100g
    ingredient.fat_per_100g = payload.fat_per_100g
    db.add(ingredient)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ingredient already exists")
    db.refresh(ingredient)
    return ingredient


@app.delete("/ingredients/{ingredient_id}", status_code=204)
def delete_ingredient(
    ingredient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ingredient = get_ingredient(ingredient_id, db)
    linked_recipes = db.scalars(
        select(Recipe.name)
        .join(RecipeIngredient, Recipe.id == RecipeIngredient.recipe_id)
        .where(
            RecipeIngredient.ingredient_id == ingredient_id,
        )
        .order_by(Recipe.name.asc())
    ).all()
    if linked_recipes:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ingredient cannot be deleted because it is used in {len(linked_recipes)} "
                f"recipe(s): {', '.join(linked_recipes[:5])}"
            ),
        )
    db.delete(ingredient)
    db.commit()


@app.get("/recipes", response_model=list[RecipeRead])
def list_recipes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RecipeRead]:
    recipes = db.scalars(
        select(Recipe)
        .where(Recipe.user_id == current_user.id)
        .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .order_by(Recipe.created_at.desc())
    ).unique().all()
    return [serialize_recipe(recipe) for recipe in recipes]


@app.post("/recipes", response_model=RecipeRead, status_code=201)
def create_recipe(
    payload: RecipeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipeRead:
    existing = db.scalar(select(Recipe).where(Recipe.name.ilike(payload.name)))
    if existing and existing.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Recipe already exists")

    ingredient_ids = [item.ingredient_id for item in payload.ingredients]
    ingredients = db.scalars(
        select(Ingredient).where(Ingredient.id.in_(ingredient_ids))
    ).all()
    ingredient_map = {ingredient.id: ingredient for ingredient in ingredients}

    missing_ids = [ingredient_id for ingredient_id in ingredient_ids if ingredient_id not in ingredient_map]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Missing ingredients: {missing_ids}")

    recipe = Recipe(
        name=payload.name,
        instructions=payload.instructions,
        prep_time_minutes=payload.prep_time_minutes,
        total_yield_grams=0,
        user_id=current_user.id,
    )
    db.add(recipe)
    db.flush()

    for item in payload.ingredients:
        recipe.ingredients.append(
            RecipeIngredient(
                ingredient_id=item.ingredient_id,
                amount_grams=item.amount_grams,
            )
        )

    recipe.total_yield_grams = recipe_total_yield_grams(recipe)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Recipe already exists")
    recipe = (
        db.execute(
            select(Recipe)
            .where(Recipe.id == recipe.id, Recipe.user_id == current_user.id)
            .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        )
        .scalars()
        .unique()
        .one()
    )
    return serialize_recipe(recipe)


@app.put("/recipes/{recipe_id}", response_model=RecipeRead)
def update_recipe(
    recipe_id: int,
    payload: RecipeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipeRead:
    recipe = get_owned_recipe(recipe_id, current_user, db)
    duplicate = db.scalar(
        select(Recipe).where(
            Recipe.name.ilike(payload.name),
            Recipe.user_id == current_user.id,
            Recipe.id != recipe_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Recipe already exists")

    ingredient_ids = [item.ingredient_id for item in payload.ingredients]
    ingredients = db.scalars(
        select(Ingredient).where(Ingredient.id.in_(ingredient_ids))
    ).all()
    ingredient_map = {ingredient.id: ingredient for ingredient in ingredients}
    missing_ids = [ingredient_id for ingredient_id in ingredient_ids if ingredient_id not in ingredient_map]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Missing ingredients: {missing_ids}")

    recipe.name = payload.name
    recipe.instructions = payload.instructions
    recipe.prep_time_minutes = payload.prep_time_minutes
    recipe.ingredients.clear()
    db.flush()

    for item in payload.ingredients:
        recipe.ingredients.append(
            RecipeIngredient(
                ingredient_id=item.ingredient_id,
                amount_grams=item.amount_grams,
            )
        )

    recipe.total_yield_grams = recipe_total_yield_grams(recipe)
    db.add(recipe)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Recipe already exists")
    return serialize_recipe(get_owned_recipe(recipe_id, current_user, db))


@app.delete("/recipes/{recipe_id}", status_code=204)
def delete_recipe(
    recipe_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    recipe = get_owned_recipe(recipe_id, current_user, db)
    linked_entry_ids = db.scalars(
        select(MealEntry.id).where(
            MealEntry.recipe_id == recipe_id,
            MealEntry.user_id == current_user.id,
        )
    ).all()
    if linked_entry_ids:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Recipe cannot be deleted because it is used in {len(linked_entry_ids)} "
                "meal entr(y/ies). Delete those meals first."
            ),
        )
    db.delete(recipe)
    db.commit()


@app.post("/recipes/{recipe_id}/prepare", response_model=list[InventoryItemRead])
def prepare_recipe(
    recipe_id: int,
    payload: RecipePrepareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[InventoryItem]:
    recipe = get_owned_recipe(recipe_id, current_user, db)
    if payload.consume_inventory:
        for recipe_item in recipe.ingredients:
            inventory_item = db.scalar(
                select(InventoryItem).where(
                    InventoryItem.user_id == current_user.id,
                    InventoryItem.ingredient_id == recipe_item.ingredient_id,
                )
            )
            if not inventory_item:
                continue
            if inventory_item.amount_grams is None or inventory_item.amount_grams <= recipe_item.amount_grams:
                db.delete(inventory_item)
            else:
                inventory_item.amount_grams = round(inventory_item.amount_grams - recipe_item.amount_grams, 2)
                db.add(inventory_item)

    db.commit()
    return db.scalars(inventory_items_query(current_user)).all()


@app.get("/meal-entries", response_model=list[MealEntryRead])
def list_meal_entries(
    target_date: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MealEntryRead]:
    query = (
        select(MealEntry)
        .where(MealEntry.user_id == current_user.id)
        .options(joinedload(MealEntry.recipe).joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .order_by(MealEntry.created_at.desc())
    )

    if target_date is not None:
        query = query.where(MealEntry.date == target_date)

    entries = db.scalars(query).unique().all()
    return [serialize_meal_entry(entry) for entry in entries]


@app.post("/meal-entries", response_model=MealEntryRead, status_code=201)
def create_meal_entry(
    payload: MealEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealEntryRead:
    recipe = get_owned_recipe(payload.recipe_id, current_user, db)

    entry = MealEntry(**payload.model_dump(), user_id=current_user.id)
    db.add(entry)
    db.commit()
    entry = (
        db.execute(
            select(MealEntry)
            .where(MealEntry.id == entry.id)
            .options(joinedload(MealEntry.recipe).joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        )
        .scalars()
        .unique()
        .one()
    )
    return serialize_meal_entry(entry)


@app.put("/meal-entries/{meal_entry_id}", response_model=MealEntryRead)
def update_meal_entry(
    meal_entry_id: int,
    payload: MealEntryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealEntryRead:
    entry = get_owned_meal_entry(meal_entry_id, current_user, db)
    get_owned_recipe(payload.recipe_id, current_user, db)

    entry.recipe_id = payload.recipe_id
    entry.meal_type = payload.meal_type
    entry.date = payload.date
    entry.grams_eaten = payload.grams_eaten
    entry.note = payload.note

    db.add(entry)
    db.commit()
    return serialize_meal_entry(get_owned_meal_entry(meal_entry_id, current_user, db))


@app.delete("/meal-entries/{meal_entry_id}", status_code=204)
def delete_meal_entry(
    meal_entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    entry = get_owned_meal_entry(meal_entry_id, current_user, db)
    db.delete(entry)
    db.commit()
