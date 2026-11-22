from datetime import datetime, timedelta, timezone
from os import getenv

import jwt
import pytest
from fastapi.testclient import TestClient

from billing_api.main import app
from billing_api.routers import bills


DETAILS_URL = "/api/v1/subscribers/A001/bills/2026/10/details"
client = TestClient(app)


@pytest.fixture
def signing_key(monkeypatch):
    key = "test-only-key-for-billing-api-and-never-for-deployment"
    monkeypatch.setenv("BILLING_JWT_SECRET", key)
    return key


def signed_headers(signing_key, subscriber_no, expires_in):
    claims = {
        "sub": subscriber_no,
        "exp": datetime.now(timezone.utc) + expires_in,
    }
    token = jwt.encode(claims, signing_key, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_bill_details_requires_bearer_token():
    response = client.get(DETAILS_URL)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_bill_details_rejects_invalid_token(signing_key):
    response = client.get(DETAILS_URL, headers={"Authorization": "Bearer invalid"})

    assert response.status_code == 401


def test_bill_details_rejects_expired_token(signing_key):
    headers = signed_headers(signing_key, "A001", timedelta(minutes=-1))
    response = client.get(DETAILS_URL, headers=headers)

    assert response.status_code == 401


def test_bill_details_forbids_access_to_another_subscriber(signing_key):
    headers = signed_headers(signing_key, "B001", timedelta(minutes=5))
    response = client.get(DETAILS_URL, headers=headers)

    assert response.status_code == 403


DEMO_BILL = {
    "phone_minutes": 1350,
    "internet_mb": 35000,
    "phone_charge_cents": 1000,
    "internet_charge_cents": 7000,
    "paid_cents": 0,
}


@pytest.fixture
def subscriber_headers(signing_key):
    return signed_headers(signing_key, "A001", timedelta(minutes=5))


def test_bill_details_returns_the_owners_bill(monkeypatch, subscriber_headers):
    def find_bill(subscriber_no, year, month):
        assert (subscriber_no, year, month) == ("A001", 2026, 10)
        return DEMO_BILL

    monkeypatch.setattr(bills, "find_bill", find_bill, raising=False)

    response = client.get(DETAILS_URL, headers=subscriber_headers)

    assert response.status_code == 200
    assert response.json() == {
        "subscriberNo": "A001",
        "year": 2026,
        "month": 10,
        "currency": "USD",
        "total": "80.00",
        "paidAmount": "0.00",
        "remainingBalance": "80.00",
        "phoneMinutes": 1350,
        "internetMb": 35000,
        "internetGb": "35.000",
        "chargeBreakdown": [
            {"type": "phone", "amount": "10.00"},
            {"type": "internet", "amount": "70.00"},
        ],
        "page": 1,
        "pageSize": 10,
        "totalItems": 2,
    }


def test_bill_details_paginates_charges_and_keeps_the_summary(
    monkeypatch, subscriber_headers
):
    monkeypatch.setattr(bills, "find_bill", lambda *_: DEMO_BILL, raising=False)

    response = client.get(
        DETAILS_URL, params={"page": 2, "pageSize": 1}, headers=subscriber_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == "80.00"
    assert body["totalItems"] == 2
    assert body["page"] == 2
    assert body["pageSize"] == 1
    assert body["chargeBreakdown"] == [{"type": "internet", "amount": "70.00"}]


def test_bill_details_returns_not_found_for_a_missing_period(
    monkeypatch, subscriber_headers
):
    monkeypatch.setattr(bills, "find_bill", lambda *_: None, raising=False)

    response = client.get(DETAILS_URL, headers=subscriber_headers)

    assert response.status_code == 404


def test_bill_details_reports_an_unavailable_database(
    monkeypatch, subscriber_headers
):
    monkeypatch.delenv("BILLING_DATABASE_URL", raising=False)

    response = client.get(DETAILS_URL, headers=subscriber_headers)

    assert response.status_code == 503


def test_bill_details_reads_the_docker_postgres_fixture(
    monkeypatch, subscriber_headers
):
    test_url = getenv("BILLING_TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("Set BILLING_TEST_DATABASE_URL to the local demo database")
    monkeypatch.setenv("BILLING_DATABASE_URL", test_url)

    response = client.get(DETAILS_URL, headers=subscriber_headers)

    assert response.status_code == 200
    assert response.json()["total"] == "80.00"
    assert response.json()["internetMb"] == 35000
