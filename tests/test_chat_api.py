import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx2
import jwt
import pytest
from fastapi.testclient import TestClient

from billing_api.main import app as billing_app
from billing_api.routers import bills
from mcp_server.server import create_app as create_mcp_app


CHAT_URL = "/api/v1/chat"
QUESTION = "Ekim 2026'da internet ücretim neden $70?"


def tool_request(name, call_id, arguments):
    return SimpleNamespace(
        status="completed",
        output=[SimpleNamespace(
            type="function_call",
            name=name,
            call_id=call_id,
            arguments=json.dumps(arguments),
        )],
    )


def test_chat_rejects_requests_without_a_session():
    from agent.chat_api import create_app

    async def model(**_request):
        pytest.fail("Chat must reject an unauthenticated request before calling the model")

    with TestClient(create_app(create_response=model)) as client:
        reply = client.post(CHAT_URL, json={"question": QUESTION})

    assert reply.status_code == 401
    assert reply.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("include_dialogue", [False, True], ids=["default", "with_dialogue"])
def test_chat_returns_answer_and_tool_trace_for_authenticated_subscriber(
    monkeypatch, include_dialogue,
):
    from agent.chat_api import create_app

    signing_key = "chat-test-only-key-never-for-deployment"
    monkeypatch.setenv("BILLING_JWT_SECRET", signing_key)
    token = jwt.encode(
        {"sub": "A001", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        signing_key,
        algorithm="HS256",
    )
    bill_reads = []

    def find_bill(subscriber_no, year, month):
        bill_reads.append((subscriber_no, year, month))
        return {
            "phone_minutes": 1350,
            "internet_mb": 35000,
            "phone_charge_cents": 1000,
            "internet_charge_cents": 7000,
            "paid_cents": 0,
        }

    monkeypatch.setattr(bills, "find_bill", find_bill)
    answer = "35 GB için $50 taban ücret ve $20 ek blok ücreti faturana yansıdı. [§3.2]"

    async def model(**request):
        if len(request["input"]) == 1:
            assert request["input"][0] == {"role": "user", "content": QUESTION}
            return tool_request("query_bill_details", "details", {"year": 2026, "month": 10})

        tool_output = request["input"][-1]
        result = json.loads(tool_output["output"])
        if tool_output["call_id"] == "details":
            assert result["internetMb"] == 35000
            return tool_request(
                "search_billing_documentation", "policy",
                {"query": "extra internet cost beyond 20 GB"},
            )

        assert tool_output["call_id"] == "policy"
        assert any(passage["section"] == "3.2" for passage in result["passages"])
        return SimpleNamespace(status="completed", output=[], output_text=answer)

    async def check():
        mcp_app = create_mcp_app()
        chat_app = create_app(
            create_response=model,
            billing_transport=httpx2.ASGITransport(app=billing_app),
            mcp_transport=httpx2.ASGITransport(app=mcp_app),
            include_dialogue=include_dialogue,
        )
        async with (
            mcp_app.router.lifespan_context(mcp_app),
            chat_app.router.lifespan_context(chat_app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=chat_app),
                base_url="http://chat.test",
                trust_env=False,
            ) as client,
        ):
            reply = await client.post(
                CHAT_URL, json={"question": QUESTION},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert reply.status_code == 200, reply.text
        assert bill_reads == [("A001", 2026, 10)]
        body = reply.json()
        assert body["answer"] == answer
        assert [call["name"] for call in body["tool_trace"]] == [
            "query_bill_details", "search_billing_documentation",
        ]
        assert body["tool_trace"][0]["arguments"] == {"year": 2026, "month": 10}
        assert {"type": "internet", "amount": "70.00"} in (
            body["tool_trace"][0]["result"]["chargeBreakdown"]
        )
        assert token not in reply.text

        if include_dialogue:
            dialogue = body["dialogue"]
            assert [step["kind"] for step in dialogue] == [
                "request", "tool_call", "tool_result", "tool_call", "tool_result", "answer",
            ]
            request, details_call, details_result, guide_call, guide_result, final = (
                step["payload"] for step in dialogue
            )
            assert request["question"] == QUESTION
            assert [tool["name"] for tool in request["tools"]] == [
                "search_billing_documentation", "query_bill", "query_bill_details",
                "prepare_bill_payment",
            ]
            assert details_call == {
                "name": "query_bill_details",
                "call_id": "details",
                "arguments": {"year": 2026, "month": 10},
            }
            assert details_result["call_id"] == details_call["call_id"]
            assert details_result["result"] == body["tool_trace"][0]["result"]
            assert guide_call["arguments"] == {"query": "extra internet cost beyond 20 GB"}
            assert guide_result["call_id"] == guide_call["call_id"] == "policy"
            assert guide_result["result"] == body["tool_trace"][1]["result"]
            assert final == {"answer": answer}
        else:
            assert "dialogue" not in body

    asyncio.run(check())
