import jwt
import httpx2
import pytest
from fastapi.testclient import TestClient

from agent import chat_api


LOGIN = "/api/v1/auth/login"
PREPARE = "/api/v1/operator/operations/prepare"
CONFIRM = "/api/v1/operator/operations/confirm"
TEST_KEY = "operator-login-fixture-never-for-deployment"


@pytest.fixture
def operator_app(monkeypatch):
    monkeypatch.setenv("BILLING_JWT_SECRET", TEST_KEY)
    monkeypatch.setenv("BILLING_API_BASE_URL", "http://billing.test/gateway-stage")
    return monkeypatch


def test_operator_login_issues_scope_from_registered_credentials(operator_app):
    from agent.operator_accounts import password_digest

    salt = bytes(16)
    stored = (salt, password_digest("operator-fixture-password", salt))
    operator_app.setattr(chat_api, "find_operator_credentials", lambda name: (
        stored if name == "demo-operator" else None
    ))
    with TestClient(chat_api.create_app(demo_password="subscriber-fixture")) as client:
        wrong = client.post(LOGIN, json={"username": "demo-operator", "password": "wrong"})
        assert wrong.status_code == 401
        login = client.post(LOGIN, json={
            "username": "demo-operator", "password": "operator-fixture-password",
        })
        subscriber = client.post(LOGIN, json={
            "username": "A001", "password": "subscriber-fixture",
        })

    assert login.status_code == 200
    assert login.json()["role"] == "operator"
    claims = jwt.decode(login.json()["token"], TEST_KEY, algorithms=["HS256"])
    assert claims["sub"] == "operator:demo-operator"
    assert claims["scope"] == "billing:write"
    assert subscriber.json()["role"] == "subscriber"
    assert "scope" not in jwt.decode(subscriber.json()["token"], TEST_KEY, algorithms=["HS256"])


@pytest.mark.parametrize(("kind", "billing_route", "extra"), [
    ("add_usage", "usage", {"usageType": "Internet"}),
    ("calculate_bill", "bills/calculate", {}),
])
def test_operator_write_requires_explicit_one_time_confirmation(
    operator_app, kind, billing_route, extra,
):
    import json

    calls = []
    period = {"subscriberNo": "A001", "month": 12, "year": 2026, **extra}

    def auth(scope="", subject="operator:demo-operator"):
        from datetime import datetime, timedelta, timezone

        token = jwt.encode({
            "sub": subject, "scope": scope,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }, TEST_KEY, algorithm="HS256")
        return {"Authorization": "Bearer " + token}

    owner = auth("billing:write")

    def billing(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == "/gateway-stage/api/v1/" + billing_route
        assert request.headers["Authorization"] == owner["Authorization"]
        assert json.loads(request.content) == period
        return httpx2.Response(200, json={"status": "success"})

    app = chat_api.create_app(billing_transport=httpx2.MockTransport(billing))
    operation = {"kind": kind, "billing": period}
    with TestClient(app) as client:
        assert client.post(PREPARE, json=operation).status_code == 401
        assert client.post(PREPARE, headers=auth(subject="A001"), json=operation).status_code == 403
        prepared = client.post(PREPARE, headers=owner, json=operation)
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["operation"] == operation
        assert calls == []

        approval = {"confirmation_id": prepared.json()["confirmation_id"]}
        other = auth("billing:write", subject="operator:another")
        assert client.post(CONFIRM, headers=other, json=approval).status_code == 404
        approved = client.post(CONFIRM, headers=owner, json=approval)
        assert approved.status_code == 200
        assert approved.json() == {"status": "success"}
        assert client.post(CONFIRM, headers=owner, json=approval).status_code == 409

    assert len(calls) == 1
