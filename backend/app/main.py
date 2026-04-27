from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .database import get_db, init_db
from .models import Ingredient, LoginAudit, MealEntry, Recipe, RecipeIngredient, User
from .schemas import (
    AuthResponse,
    AdminIngredientRead,
    AdminMealEntryRead,
    AdminRecipeRead,
    AdminUserRead,
    DailySummaryRead,
    DeficitReportRead,
    IngredientCreate,
    LoginAuditRead,
    IngredientRead,
    IngredientUpdate,
    LoginRequest,
    MealEntryCreate,
    MealEntryRead,
    MealEntryUpdate,
    RecipeUpdate,
    RegisterRequest,
    RecipeCreate,
    RecipeRead,
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

init_db()

app = FastAPI(title="Calry API", version="0.1.0")
security = HTTPBearer(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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

    return [
        AdminUserRead(
            **serialize_user(user).model_dump(),
            ingredient_count=ingredient_counts.get(user.id, 0),
            recipe_count=recipe_counts.get(user.id, 0),
            meal_entry_count=meal_counts.get(user.id, 0),
        )
        for user in users
    ]


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
            calories_per_100g=ingredient.calories_per_100g,
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
    duplicate = db.scalar(select(Ingredient).where(Ingredient.name.ilike(payload.name)))
    if duplicate:
        raise HTTPException(status_code=400, detail="Ingredient already exists")

    ingredient = Ingredient(
        user_id=current_admin.id,
        name=payload.name,
        calories_per_100g=payload.calories_per_100g,
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
        calories_per_100g=ingredient.calories_per_100g,
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
                total_yield_grams=recipe.total_yield_grams,
                total_calories=serialized.total_calories,
                calories_per_100g=serialized.calories_per_100g,
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
    existing = db.scalar(select(Ingredient).where(Ingredient.name.ilike(payload.name)))
    if existing:
        raise HTTPException(status_code=400, detail="Ingredient already exists")

    ingredient = Ingredient(**payload.model_dump(), user_id=current_user.id)
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
    duplicate = db.scalar(
        select(Ingredient).where(
            Ingredient.name.ilike(payload.name),
            Ingredient.id != ingredient_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Ingredient already exists")

    ingredient.name = payload.name
    ingredient.calories_per_100g = payload.calories_per_100g
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

    recipe = Recipe(name=payload.name, total_yield_grams=0, user_id=current_user.id)
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
