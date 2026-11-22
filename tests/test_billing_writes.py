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
USAGE_URL = "/api/v1/usage"
CALCULATE_URL = "/api/v1/bills/calculate"
PERIOD = {"subscriberNo": "A001", "year": 2026, "month": 11}


@pytest.fixture
def token_headers(monkeypatch):
    key = "test-only-key-for-billing-writes-and-never-for-deployment"
    monkeypatch.setenv("BILLING_JWT_SECRET", key)

    def make_token(subscriber_no, scope=""):
        token = jwt.encode(
            {
                "sub": subscriber_no,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                "scope": scope,
            },
            key,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return make_token


@pytest.mark.parametrize(
    ("url", "body"),
    [(USAGE_URL, {**PERIOD, "usageType": "Phone"}), (CALCULATE_URL, PERIOD)],
)
def test_billing_writes_require_an_authorized_operator(url, body, token_headers):
    assert client.post(url, json=body).status_code == 401
    response = client.post(url, json=body, headers=token_headers("A001"))
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("usage_type", "minutes", "mb"), [("Phone", 10, 0), ("Internet", 0, 1)]
)
def test_add_usage_applies_the_fixed_increment(
    monkeypatch, token_headers, usage_type, minutes, mb
):
    def record_usage(subscriber_no, year, month, phone_minutes, internet_mb):
        assert (subscriber_no, year, month) == ("A001", 2026, 11)
        assert (phone_minutes, internet_mb) == (minutes, mb)
        return True

    monkeypatch.setattr(bills, "record_usage", record_usage, raising=False)
    response = client.post(
        USAGE_URL,
        json={**PERIOD, "usageType": usage_type},
        headers=token_headers("operator", "billing:write"),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}


def test_add_usage_rejects_an_unknown_usage_type(token_headers):
    response = client.post(
        USAGE_URL,
        json={**PERIOD, "usageType": "Video"},
        headers=token_headers("operator", "billing:write"),
    )

    assert response.status_code == 422


def test_calculate_bill_saves_a_selected_period(monkeypatch, token_headers):
    def recalculate_bill(subscriber_no, year, month):
        assert (subscriber_no, year, month) == ("A001", 2026, 11)
        return True

    monkeypatch.setattr(bills, "recalculate_bill", recalculate_bill, raising=False)
    response = client.post(
        CALCULATE_URL, json=PERIOD, headers=token_headers("operator", "billing:write")
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}


def test_calculate_bill_rejects_an_unknown_subscriber(monkeypatch, token_headers):
    monkeypatch.setattr(bills, "recalculate_bill", lambda *_: False, raising=False)
    response = client.post(
        CALCULATE_URL, json=PERIOD, headers=token_headers("operator", "billing:write")
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Subscriber not found"


@pytest.mark.parametrize(
    ("minutes", "mb", "expected"),
    [
        (0, 0, (0, 5000)),
        (1000, 20000, (0, 5000)),
        (1001, 20001, (1000, 6000)),
        (2000, 30000, (1000, 6000)),
        (2001, 30001, (2000, 7000)),
        (1350, 35000, (1000, 7000)),
    ],
)
def test_calculate_charges_counts_started_blocks(minutes, mb, expected):
    from billing_api.services.pricing import calculate_charges

    assert calculate_charges(minutes, mb) == expected


def test_usage_and_calculation_persist_to_postgres(monkeypatch, token_headers):
    database_url = getenv("BILLING_TEST_WRITE_DATABASE_URL")
    if not database_url:
        pytest.skip("Set BILLING_TEST_WRITE_DATABASE_URL to the dedicated write test DB")

    with psycopg.connect(database_url) as connection:
        assert connection.info.dbname == "billing_usage_test"
        subscriber_no = f"TEST-{uuid4().hex}"
        connection.execute(
            "INSERT INTO subscribers (subscriber_no) VALUES (%s)", (subscriber_no,)
        )
        connection.execute(
            """
            INSERT INTO monthly_usage
                (subscriber_no, bill_year, bill_month, phone_minutes, internet_mb)
            VALUES (%s, 2026, 11, 1000, 20000)
            """,
            (subscriber_no,),
        )

    monkeypatch.setenv("BILLING_DATABASE_URL", database_url)
    period = {**PERIOD, "subscriberNo": subscriber_no}
    operator = token_headers("operator", "billing:write")

    for usage_type in ("Phone", "Internet", "Phone", "Internet"):
        response = client.post(
            USAGE_URL, json={**period, "usageType": usage_type}, headers=operator
        )
        assert response.status_code == 200

    assert client.post(CALCULATE_URL, json=period, headers=operator).status_code == 200
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "UPDATE bills SET paid_cents = 2000 WHERE subscriber_no = %s",
            (subscriber_no,),
        )

    assert client.post(CALCULATE_URL, json=period, headers=operator).status_code == 200
    details = client.get(
        f"/api/v1/subscribers/{subscriber_no}/bills/2026/11/details",
        headers=token_headers(subscriber_no),
    )

    assert details.status_code == 200
    assert details.json()["phoneMinutes"] == 1020
    assert details.json()["internetMb"] == 20002
    assert details.json()["total"] == "70.00"
    assert details.json()["paidAmount"] == "20.00"
    assert details.json()["remainingBalance"] == "50.00"
