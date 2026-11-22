import json
from datetime import datetime, timezone

import httpx2
import jwt
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from agent import chat_api
from agent.chat_demo import create_demo_app
from billing_api.routers import bills


QUESTION = "2026'nın Ekim ayında faturamda ne kadar borç kaldı?"
ANSWER = "Ekim 2026 dönemi için kalan borcun $80.00."
DEMO_PASSWORD = "demo-password-for-automated-checks"
LOGIN_URL = "/api/v1/auth/login"


def test_demo_requires_credentials_before_issuing_a_jwt(monkeypatch):
    signing_key = "local-chat-auth-test-key-never-for-deployment"
    monkeypatch.setenv("BILLING_JWT_SECRET", signing_key)

    with TestClient(create_demo_app(demo_password=DEMO_PASSWORD), base_url="http://localhost") as client:
        assert client.post("/demo/session").status_code == 404
        assert client.post("/api/v1/chat", json={"question": QUESTION}).status_code == 401
        malformed = client.post(LOGIN_URL, json={"password": DEMO_PASSWORD})
        assert malformed.status_code == 422
        assert DEMO_PASSWORD not in malformed.text

        for username, password in (("B001", DEMO_PASSWORD), ("A001", "wrong-password")):
            rejected = client.post(LOGIN_URL, json={"username": username, "password": password})
            assert rejected.status_code == 401
            assert "token" not in rejected.json()

        login = client.post(LOGIN_URL, json={"username": "A001", "password": DEMO_PASSWORD})

    assert login.status_code == 200, login.text
    assert login.headers["cache-control"] == "no-store"
    assert DEMO_PASSWORD not in login.text
    claims = jwt.decode(
        login.json()["token"], signing_key, algorithms=["HS256"],
        options={"require": ["sub", "exp"]},
    )
    assert claims["sub"] == "A001"


@pytest.mark.parametrize("live", [False, True], ids=["offline", "live"])
def test_local_chat_routes_free_text_to_responses_only_in_live_mode(monkeypatch, live):
    signing_key = "local-chat-test-key-never-for-deployment"
    monkeypatch.setenv("BILLING_JWT_SECRET", signing_key)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-with-mock-transport")
    monkeypatch.setenv("BILLING_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:8001/mcp")
    def fixture_bill(subscriber_no, year, month, *, public_only):
        assert (subscriber_no, year, month, public_only) == ("A001", 2026, 10, False)
        return {
            "phone_minutes": 1350,
            "internet_mb": 35000,
            "phone_charge_cents": 1000,
            "internet_charge_cents": 7000,
            "paid_cents": 0,
        }

    monkeypatch.setattr(bills, "find_bill", fixture_bill)

    requests = []

    def responses_endpoint(request):
        assert request.url == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        requests.append(body)
        assert body["input"][0]["content"] == QUESTION
        assert body["model"] == "gpt-6-luna"
        assert body["store"] is False
        assert body["include"] == ["reasoning.encrypted_content"]

        if len(requests) == 1:
            output = [
                {
                    "type": "reasoning",
                    "id": "rs_fixture",
                    "summary": [],
                    "encrypted_content": "encrypted-reasoning-fixture",
                },
                {
                    "type": "function_call",
                    "id": "fc_fixture",
                    "call_id": "call_fixture",
                    "name": "query_bill",
                    "arguments": '{"year": 2026, "month": 10}',
                    "status": "completed",
                },
            ]
        else:
            assert body["input"][1]["encrypted_content"] == "encrypted-reasoning-fixture"
            assert body["input"][-1]["call_id"] == "call_fixture"
            output = [{
                "type": "message",
                "id": "msg_fixture",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": ANSWER, "annotations": []}],
            }]

        return httpx2.Response(200, json={
            "id": f"resp_{len(requests)}",
            "object": "response",
            "created_at": datetime.now(timezone.utc).timestamp(),
            "model": "gpt-6-luna",
            "status": "completed",
            "output": output,
        })

    def openai_with_mock_transport(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(responses_endpoint)
        ))

    monkeypatch.setattr(chat_api, "AsyncOpenAI", openai_with_mock_transport)
    app = create_demo_app(demo_password=DEMO_PASSWORD, live=live)
    with TestClient(app, base_url="http://localhost") as client:
        login = client.post(LOGIN_URL, json={"username": "A001", "password": DEMO_PASSWORD})
        assert login.status_code == 200, login.text
        session = login.json()
        assert session["mode"] == ("live" if live else "demo")
        reply = client.post(
            "/api/v1/chat",
            json={"question": QUESTION},
            headers={"Authorization": f"Bearer {session['token']}"},
        )

    assert reply.status_code == 200, reply.text
    if not live:
        assert requests == []
        assert reply.json()["tool_trace"] == []
        return

    assert len(requests) == 2
    result = reply.json()
    assert result["answer"] == ANSWER
    assert result["tool_trace"][0]["name"] == "query_bill"
    assert result["tool_trace"][0]["result"]["remainingBalance"] == "80.00"
    assert result["dialogue"][1]["payload"]["call_id"] == "call_fixture"
    assert result["dialogue"][2]["payload"]["call_id"] == "call_fixture"
    assert "encrypted-reasoning-fixture" not in reply.text
    assert session["token"] not in reply.text
