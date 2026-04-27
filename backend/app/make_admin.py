import sys

from sqlalchemy import select

from .database import SessionLocal, init_db
from .models import User


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m app.make_admin user@example.com", file=sys.stderr)
        return 2

    email = sys.argv[1].strip().lower()
    init_db()

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            print(f"User not found: {email}", file=sys.stderr)
            return 1

        user.is_admin = True
        db.add(user)
        db.commit()
        print(f"Admin enabled for {user.email}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
