"""Create Kemmon's first owner locally. Run from the backend folder."""
from getpass import getpass
from uuid import uuid4

from argon2 import PasswordHasher
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.main import engine


USERNAME = "kemmon.owner"


def main():
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM users WHERE role='owner')")
            ).scalar_one()
        if exists:
            print("An owner account already exists. This setup script cannot create another.")
            return

        print(f"Creating the first owner account: {USERNAME}")
        print("Enter a private password of at least 12 characters. Input will be hidden.")
        password = getpass("Owner password: ")
        if len(password) < 12 or not password.strip():
            print("Password must contain at least 12 characters and cannot be blank. Run again.")
            return
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords did not match. No account was created. Run again.")
            return

        password_hash = PasswordHasher().hash(password)
        del password, confirmation

        with engine.begin() as connection:
            # Prevent simultaneous bootstrap runs from creating two owners.
            connection.execute(text("SELECT pg_advisory_xact_lock(20261016, 1)"))
            exists = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM users WHERE role='owner')")
            ).scalar_one()
            if exists:
                print("An owner account already exists. No additional account was created.")
                return
            username_used = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM users WHERE username=:username)"),
                {"username": USERNAME},
            ).scalar_one()
            if username_used:
                print("This username already exists. Review the existing account; it was not changed.")
                return
            connection.execute(
                text("""
                    INSERT INTO users (id, username, password_hash, role, is_active)
                    VALUES (:id, :username, :password_hash, 'owner', true)
                """),
                {"id": uuid4(), "username": USERNAME, "password_hash": password_hash},
            )
        print(f"Owner account created: {USERNAME}")
        print("Next, connect the login page and owner-only staff management to this account.")
    except ProgrammingError:
        print("Staff tables are unavailable. Run 'alembic upgrade head' before this script.")
    except OperationalError:
        print("Cannot connect to PostgreSQL. Check Postgres.app and backend/.env.")
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled. No owner account was created.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
