from typing import TypedDict, cast

from billing_api.db.connection import connect as _connect
from billing_api.services.pricing import calculate_charges


class BillRecord(TypedDict):
    phone_minutes: int
    internet_mb: int
    phone_charge_cents: int
    internet_charge_cents: int
    paid_cents: int


def find_bill(
    subscriber_no: str, year: int, month: int, *, public_only: bool = False
) -> BillRecord | None:
    with _connect() as connection:
        connection.read_only = True
        record = connection.execute(
            """
            SELECT phone_minutes, internet_mb, phone_charge_cents,
                   internet_charge_cents, paid_cents
            FROM bills
            WHERE subscriber_no = %s AND bill_year = %s AND bill_month = %s
                AND (NOT %s OR public_summary)
            """,
            (subscriber_no, year, month, public_only),
        ).fetchone()

    return cast(BillRecord | None, record)


def record_usage(
    subscriber_no: str, year: int, month: int, phone_minutes: int, internet_mb: int
) -> bool:
    with _connect() as connection:
        recorded = connection.execute(
            """
            INSERT INTO monthly_usage (
                subscriber_no, bill_year, bill_month, phone_minutes, internet_mb
            )
            SELECT subscriber_no, %s, %s, %s, %s
            FROM subscribers
            WHERE subscriber_no = %s
            ON CONFLICT (subscriber_no, bill_year, bill_month) DO UPDATE SET
                phone_minutes = monthly_usage.phone_minutes + EXCLUDED.phone_minutes,
                internet_mb = monthly_usage.internet_mb + EXCLUDED.internet_mb
            RETURNING subscriber_no
            """,
            (year, month, phone_minutes, internet_mb, subscriber_no),
        ).fetchone()

    return recorded is not None


def recalculate_bill(subscriber_no: str, year: int, month: int) -> bool:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO monthly_usage (subscriber_no, bill_year, bill_month)
            SELECT subscriber_no, %s, %s
            FROM subscribers
            WHERE subscriber_no = %s
            ON CONFLICT DO NOTHING
            """,
            (year, month, subscriber_no),
        )
        usage = connection.execute(
            """
            SELECT phone_minutes, internet_mb
            FROM monthly_usage
            WHERE subscriber_no = %s AND bill_year = %s AND bill_month = %s
            FOR UPDATE
            """,
            (subscriber_no, year, month),
        ).fetchone()
        if usage is None:
            return False

        minutes, mb = usage["phone_minutes"], usage["internet_mb"]
        phone_charge, internet_charge = calculate_charges(minutes, mb)
        connection.execute(
            """
            INSERT INTO bills (
                subscriber_no, bill_year, bill_month, phone_minutes, internet_mb,
                phone_charge_cents, internet_charge_cents
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (subscriber_no, bill_year, bill_month) DO UPDATE SET
                phone_minutes = EXCLUDED.phone_minutes,
                internet_mb = EXCLUDED.internet_mb,
                phone_charge_cents = EXCLUDED.phone_charge_cents,
                internet_charge_cents = EXCLUDED.internet_charge_cents
            """,
            (subscriber_no, year, month, minutes, mb, phone_charge, internet_charge),
        )

    return True


class DuplicateTransactionId(Exception):
    pass


class InsufficientBalance(Exception):
    pass


def record_payment(
    subscriber_no: str, year: int, month: int, transaction_id: str, amount_cents: int
) -> int | None:
    period = (subscriber_no, year, month)
    with _connect() as connection:
        bill = connection.execute(
            """
            SELECT phone_charge_cents + internet_charge_cents - paid_cents AS balance
            FROM bills
            WHERE subscriber_no = %s AND bill_year = %s AND bill_month = %s
            FOR UPDATE
            """,
            period,
        ).fetchone()
        if bill is None:
            return None

        recorded = connection.execute(
            """
            INSERT INTO payments (
                transaction_id, subscriber_no, bill_year, bill_month, amount_cents
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (transaction_id) DO NOTHING
            RETURNING transaction_id
            """,
            (transaction_id, *period, amount_cents),
        ).fetchone()
        if recorded is None:
            raise DuplicateTransactionId

        balance = int(bill["balance"])
        if amount_cents > balance:
            raise InsufficientBalance

        connection.execute(
            """
            UPDATE bills SET paid_cents = paid_cents + %s
            WHERE subscriber_no = %s AND bill_year = %s AND bill_month = %s
            """,
            (amount_cents, *period),
        )

    return balance - amount_cents
