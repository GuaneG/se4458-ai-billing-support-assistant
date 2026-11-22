import argparse
import re
from getpass import getpass
from hashlib import scrypt
from os import getenv
from pathlib import Path
from secrets import token_bytes

from dotenv import dotenv_values
from psycopg import Error
from psycopg.errors import UndefinedTable

from billing_api.db.connection import connect


ROOT = Path(__file__).resolve().parents[1]
OPERATOR_SCHEMA = ROOT / "billing_api" / "db" / "operator_accounts.sql"


def password_digest(password: str, salt: bytes) -> bytes:
    return scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)


def find_operator_credentials(username: str) -> tuple[bytes, bytes] | None:
    if not getenv("BILLING_DATABASE_URL"):
        return None

    try:
        with connect() as connection:
            connection.read_only = True
            record = connection.execute(
                "SELECT password_salt, password_hash FROM operator_accounts WHERE username = %s",
                (username,),
            ).fetchone()
    except UndefinedTable:
        return None

    if record is None:
        return None
    return record["password_salt"], record["password_hash"]


def register_operator(database_url: str, username: str, password: str) -> bool:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username) or username == "a001":
        raise ValueError("Use a different operator username with 3 to 64 letters, digits, dots, underscores, or hyphens.")
    if not 1 <= len(password) <= 256:
        raise ValueError("Enter an operator password between 1 and 256 characters.")

    salt = token_bytes(16)
    digest = password_digest(password, salt)
    with connect(database_url) as connection:
        connection.execute(OPERATOR_SCHEMA.read_text(encoding="utf-8"))
        row = connection.execute(
            """
            INSERT INTO operator_accounts (username, password_salt, password_hash)
            VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING
            RETURNING username
            """,
            (username, salt, digest),
        ).fetchone()
    return row is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a billing operator account")
    parser.add_argument("username", help="Operator account username")
    args = parser.parse_args()

    database_url = getenv("BILLING_DATABASE_URL") or dotenv_values(ROOT / ".env").get("BILLING_DATABASE_URL")
    if not database_url:
        raise SystemExit("Set BILLING_DATABASE_URL before creating an operator.")

    username = args.username.strip().lower()
    password = getpass("Operatör şifresi: ")
    if password != getpass("Şifreyi tekrar gir: "):
        raise SystemExit("Passwords do not match.")

    try:
        created = register_operator(database_url, username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Error:
        raise SystemExit("Operator could not be saved. Check the database connection.") from None
    if not created:
        raise SystemExit("This operator username already exists.")
    print(f"Operator account created: {username}")


if __name__ == "__main__":
    main()
