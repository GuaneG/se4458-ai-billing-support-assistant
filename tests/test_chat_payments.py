from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx2
import jwt
import pytest
from fastapi.testclient import TestClient

from agent.chat_api import create_app
from billing_api.main import app as billing_app
from billing_api.routers import bills
from mcp_server.server import create_app as create_mcp_app


CHAT_URL = "/api/v1/chat"
CONFIRM_URL = "/api/v1/chat/payments/confirm"
QUESTION = "Ekim 2026 faturama $20 öde."


@pytest.fixture
def payment_chat(monkeypatch):
    signing_key = "chat-payment-test-key-never-for-deployment"
    monkeypatch.setenv("BILLING_JWT_SECRET", signing_key)
    monkeypatch.setenv("BILLING_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:8001/mcp")

    def bearer(subscriber_no):
        token = jwt.encode(
            {"sub": subscriber_no, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            signing_key,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    payments = []
    model_requests = []

    def find_bill(subscriber, year, month, *, public_only):
        assert (subscriber, year, month, public_only) == ("A001", 2026, 10, False)
        return {"phone_charge_cents": 1000, "internet_charge_cents": 7000, "paid_cents": 0}

    def record_payment(subscriber, year, month, transaction_id, amount_cents):
        payments.append((subscriber, year, month, transaction_id, amount_cents))
        return 6000

    monkeypatch.setattr(bills, "find_bill", find_bill)
    monkeypatch.setattr(bills, "record_payment", record_payment)

    async def model(**request):
        model_requests.append([tool["name"] for tool in request["tools"]])
        if len(request["input"]) == 1:
            call = SimpleNamespace(
                type="function_call",
                name="prepare_bill_payment",
                call_id="prepare_october_payment",
                arguments='{"year": 2026, "month": 10, "amount": "20.00"}',
            )
            return SimpleNamespace(status="completed", output=[call], output_text="")

        return SimpleNamespace(
            status="completed", output=[], output_text="Ödeme için açık onay bekleniyor."
        )

    mcp_app = create_mcp_app()

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    chat_app = create_app(
        create_response=model,
        billing_transport=httpx2.ASGITransport(app=billing_app),
        mcp_transport=httpx2.ASGITransport(app=mcp_app),
        lifespan=lifespan,
    )
    with TestClient(chat_app) as client:
        yield client, bearer, payments, model_requests


def prepare_payment(client, headers):
    reply = client.post(CHAT_URL, headers=headers, json={"question": QUESTION})
    assert reply.status_code == 200, reply.text
    pending = reply.json().get("pending_payment")
    assert pending is not None, "Chat must return the payment awaiting explicit confirmation"
    return pending


def test_chat_prepares_payment_without_writing_to_billing_api(payment_chat):
    client, bearer, payments, model_requests = payment_chat

    pending = prepare_payment(client, bearer("A001"))

    assert (pending["year"], pending["month"], pending["amount"]) == (2026, 10, "20.00")
    assert pending["confirmation_id"]
    assert "prepare_bill_payment" in model_requests[0]
    assert "pay_bill" not in model_requests[0]
    assert payments == []


def test_chat_accepts_only_the_owners_confirmation_and_pays_once(payment_chat):
    client, bearer, payments, model_requests = payment_chat
    owner = bearer("A001")
    pending = prepare_payment(client, owner)
    approval = {"confirmation_id": pending["confirmation_id"]}
    model_call_count = len(model_requests)

    assert client.post(CONFIRM_URL, json=approval).status_code == 401
    assert client.post(CONFIRM_URL, headers=bearer("B001"), json=approval).status_code == 404
    assert payments == []

    first = client.post(CONFIRM_URL, headers=owner, json=approval)
    assert first.status_code == 200, first.text
    assert first.json() == {"status": "success", "paidAmount": "20.00", "remainingBalance": "60.00"}

    repeat = client.post(CONFIRM_URL, headers=owner, json=approval)
    assert repeat.status_code == 409
    assert len(payments) == 1
    subscriber, year, month, transaction_id, amount_cents = payments[0]
    assert (subscriber, year, month, amount_cents) == ("A001", 2026, 10, 2000)
    assert transaction_id
    assert len(model_requests) == model_call_count
