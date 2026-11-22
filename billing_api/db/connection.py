from os import getenv

import psycopg
from psycopg.rows import DictRow, dict_row


def connect(database_url: str | None = None) -> psycopg.Connection[DictRow]:
    url = database_url or getenv("BILLING_DATABASE_URL")
    if not url:
        raise psycopg.OperationalError("Billing database is not configured")
    return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)
