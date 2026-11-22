from datetime import datetime, timedelta, timezone
from os import getenv
from uuid import uuid4

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from billing_api.main import app
from billing_api.routers import bills


client = TestClient(app)
SUMMARY_URL = "/api/v1/subscribers/A001/bills/2026/10"
PAYMENT_URL = f"{SUMMARY_URL}/payments"
DEMO_BILL = {
    "phone_minutes": 1350,
    "internet_mb": 35000,
    "phone_charge_cents": 1000,
    "internet_charge_cents": 7000,
    "paid_cents": 0,
}


@pytest.fixture
def bearer(monkeypatch):
    key = "test-only-key-for-payment-and-summary-checks"
    monkeypatch.setenv("BILLING_JWT_SECRET", key)

    def headers(subscriber_no):
        token = jwt.encode(
            {
                "sub": subscriber_no,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            key,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return headers


def test_query_bill_returns_the_anonymous_demo_summary(monkeypatch):
    def find_bill(subscriber, year, month, *, public_only):
        assert (subscriber, year, month, public_only) == ("A001", 2026, 10, True)
        return DEMO_BILL

    monkeypatch.setattr(bills, "find_bill", find_bill)

    response = client.get(SUMMARY_URL)

    assert response.status_code == 200
    assert response.json() == {
        "total": "80.00",
        "paidAmount": "0.00",
        "remainingBalance": "80.00",
        "status": "unpaid",
    }


def test_query_bill_does_not_fall_back_to_anonymous_for_bad_credentials(monkeypatch):
    monkeypatch.setattr(bills, "find_bill", lambda *args, **kwargs: DEMO_BILL)

    response = client.get(SUMMARY_URL, headers={"Authorization": "Basic invalid"})

    assert response.status_code == 401


def test_query_bill_forbids_a_token_for_another_subscriber(bearer):
    response = client.get(SUMMARY_URL, headers=bearer("B001"))

    assert response.status_code == 403


def test_pay_bill_requires_its_owners_token(bearer):
    payload = {"amount": "20.00", "transactionId": "se4458-test"}
    assert client.post(PAYMENT_URL, json=payload).status_code == 401
    response = client.post(PAYMENT_URL, json=payload, headers=bearer("B001"))
    assert response.status_code == 403


@pytest.mark.parametrize("amount", ["0.00", "-0.01", "10.001"])
def test_pay_bill_rejects_invalid_amounts(amount, bearer):
    response = client.post(
        PAYMENT_URL,
        json={"amount": amount, "transactionId": "se4458-test"},
        headers=bearer("A001"),
    )

    assert response.status_code == 422


def test_pay_bill_reports_the_payment_and_new_balance(monkeypatch, bearer):
    def record_payment(subscriber, year, month, transaction_id, amount_cents):
        assert (subscriber, year, month) == ("A001", 2026, 10)
        assert (transaction_id, amount_cents) == ("se4458-test", 2000)
        return 6000

    monkeypatch.setattr(bills, "record_payment", record_payment, raising=False)

    response = client.post(
        PAYMENT_URL,
        json={"amount": "20.00", "transactionId": "se4458-test"},
        headers=bearer("A001"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success", "paidAmount": "20.00", "remainingBalance": "60.00"
    }


def test_query_and_pay_bill_use_one_consistent_postgres_balance(monkeypatch, bearer):
    database_url = getenv("BILLING_TEST_WRITE_DATABASE_URL")
    if not database_url:
        pytest.skip("Set BILLING_TEST_WRITE_DATABASE_URL to the dedicated write test DB")

    suffix = uuid4().hex
    subscriber = f"PAY-TEST-{suffix}"
    with psycopg.connect(database_url) as connection:
        assert connection.info.dbname == "billing_usage_test"
        connection.execute(
            """
            INSERT INTO bills (
                subscriber_no, bill_year, bill_month, phone_minutes, internet_mb,
                phone_charge_cents, internet_charge_cents
            ) VALUES (%s, 2026, 10, 1350, 35000, 1000, 7000)
            """,
            (subscriber,),
        )

    monkeypatch.setenv("BILLING_DATABASE_URL", database_url)
    summary_url = f"/api/v1/subscribers/{subscriber}/bills/2026/10"
    payment_url = f"{summary_url}/payments"
    headers = bearer(subscriber)
    first = {"amount": "20.00", "transactionId": f"partial-{suffix}"}

    assert client.get(summary_url).status_code == 404
    assert client.get(summary_url, headers=headers).json()["total"] == "80.00"
    assert client.post(payment_url, json=first, headers=headers).status_code == 200

    duplicate = client.post(payment_url, json=first, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Transaction ID already exists"
    assert client.get(summary_url, headers=headers).json() == {
        "total": "80.00",
        "paidAmount": "20.00",
        "remainingBalance": "60.00",
        "status": "unpaid",
    }

    last_id = f"settle-{suffix}"
    overpayment = client.post(
        payment_url, json={"amount": "60.01", "transactionId": last_id}, headers=headers
    )
    assert overpayment.status_code == 409
    assert overpayment.json()["detail"] == "Amount exceeds the remaining balance"
    settled = client.post(
        payment_url, json={"amount": "60.00", "transactionId": last_id}, headers=headers
    )
    assert settled.status_code == 200
    assert client.get(summary_url, headers=headers).json() == {
        "total": "80.00",
        "paidAmount": "80.00",
        "remainingBalance": "0.00",
        "status": "paid",
    }

    with psycopg.connect(database_url) as connection:
        count = connection.execute(
            "SELECT count(*) FROM payments WHERE subscriber_no = %s", (subscriber,)
        ).fetchone()[0]
    assert count == 2
