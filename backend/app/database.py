import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./calry.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_legacy_schema()


def migrate_legacy_schema() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    if "users" in existing_tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        statements = []
        if "email" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
        if "password_hash" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
        if "auth_token" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN auth_token VARCHAR(255)")
        if "is_admin" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
        if "ai_enabled" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN ai_enabled BOOLEAN DEFAULT 0")
        if "failed_login_attempts" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0")
        if "locked_until" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN locked_until DATETIME")
        if "daily_calorie_goal" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN daily_calorie_goal INTEGER")
        _run_statements(statements)

    if "ingredients" in existing_tables:
        ingredient_columns = {column["name"] for column in inspector.get_columns("ingredients")}
        statements = []
        if "user_id" not in ingredient_columns:
            statements.append("ALTER TABLE ingredients ADD COLUMN user_id INTEGER")
        if "protein_per_100g" not in ingredient_columns:
            statements.append("ALTER TABLE ingredients ADD COLUMN protein_per_100g FLOAT DEFAULT 0 NOT NULL")
        if "carbs_per_100g" not in ingredient_columns:
            statements.append("ALTER TABLE ingredients ADD COLUMN carbs_per_100g FLOAT DEFAULT 0 NOT NULL")
        if "fat_per_100g" not in ingredient_columns:
            statements.append("ALTER TABLE ingredients ADD COLUMN fat_per_100g FLOAT DEFAULT 0 NOT NULL")
        _run_statements(statements)

    if "recipes" in existing_tables:
        recipe_columns = {column["name"] for column in inspector.get_columns("recipes")}
        statements = []
        if "prep_time_minutes" not in recipe_columns:
            statements.append("ALTER TABLE recipes ADD COLUMN prep_time_minutes INTEGER")
        _run_statements(statements)
        _migrate_name_unique_table("ingredients")

    if "recipes" in existing_tables:
        recipe_columns = {column["name"] for column in inspector.get_columns("recipes")}
        statements = []
        if "user_id" not in recipe_columns:
            statements.append("ALTER TABLE recipes ADD COLUMN user_id INTEGER")
        if "instructions" not in recipe_columns:
            statements.append("ALTER TABLE recipes ADD COLUMN instructions VARCHAR(4000)")
        _run_statements(statements)
        _migrate_name_unique_table("recipes")

    if "inventory_items" in existing_tables:
        inventory_columns = {column["name"] for column in inspector.get_columns("inventory_items")}
        statements = []
        if "amount_grams" not in inventory_columns:
            statements.append("ALTER TABLE inventory_items ADD COLUMN amount_grams FLOAT")
        _run_statements(statements)

    if "shopping_list_items" in existing_tables:
        shopping_columns = {column["name"] for column in inspector.get_columns("shopping_list_items")}
        statements = []
        if "amount_grams" not in shopping_columns:
            statements.append("ALTER TABLE shopping_list_items ADD COLUMN amount_grams FLOAT")
        if "is_purchased" not in shopping_columns:
            statements.append("ALTER TABLE shopping_list_items ADD COLUMN is_purchased BOOLEAN DEFAULT 0")
        if "purchased_at" not in shopping_columns:
            statements.append("ALTER TABLE shopping_list_items ADD COLUMN purchased_at DATETIME")
        _run_statements(statements)


def _run_statements(statements: list[str]) -> None:
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _migrate_name_unique_table(table_name: str) -> None:
    inspector = inspect(engine)
    unique_constraints = inspector.get_unique_constraints(table_name)
    has_global_name_unique = any(
        constraint.get("column_names") == ["name"] for constraint in unique_constraints
    )

    if not has_global_name_unique:
        return

    if table_name == "ingredients":
        create_sql = """
        CREATE TABLE ingredients_new (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            name VARCHAR(120) NOT NULL,
            calories_per_100g FLOAT NOT NULL,
            protein_per_100g FLOAT NOT NULL DEFAULT 0,
            carbs_per_100g FLOAT NOT NULL DEFAULT 0,
            fat_per_100g FLOAT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL
        )
        """
        copy_sql = """
        INSERT INTO ingredients_new (
            id, user_id, name, calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, created_at
        )
        SELECT
            id,
            user_id,
            name,
            calories_per_100g,
            COALESCE(protein_per_100g, 0),
            COALESCE(carbs_per_100g, 0),
            COALESCE(fat_per_100g, 0),
            created_at
        FROM ingredients
        """
        unique_name = "uq_ingredients_user_name"
    else:
        create_sql = """
        CREATE TABLE recipes_new (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            name VARCHAR(120) NOT NULL,
            instructions VARCHAR(4000),
            total_yield_grams FLOAT NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
        copy_sql = """
        INSERT INTO recipes_new (id, user_id, name, instructions, total_yield_grams, created_at)
        SELECT id, user_id, name, instructions, total_yield_grams, created_at FROM recipes
        """
        unique_name = "uq_recipes_user_name"

    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(text(create_sql))
        connection.execute(text(copy_sql))
        connection.execute(text(f"DROP TABLE {table_name}"))
        connection.execute(text(f"ALTER TABLE {table_name}_new RENAME TO {table_name}"))
        connection.execute(text(f"CREATE UNIQUE INDEX {unique_name} ON {table_name}(user_id, name)"))
        connection.execute(text(f"CREATE INDEX ix_{table_name}_user_id ON {table_name}(user_id)"))
        connection.execute(text("PRAGMA foreign_keys=ON"))
