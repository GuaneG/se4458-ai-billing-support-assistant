import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx2
import jwt
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from mcp_server.server import create_app


def response(*output, text=""):
    return SimpleNamespace(status="completed", output=list(output), output_text=text)


def function_call(name, arguments, call_id="call_guide"):
    return SimpleNamespace(
        type="function_call", name=name, arguments=arguments, call_id=call_id
    )


def test_agent_returns_a_real_mcp_result_to_the_model():
    from agent.billing_agent import ask_billing_guide

    async def check():
        requests = []
        query = "extra internet cost beyond 20 GB"
        reasoning_item = SimpleNamespace(type="reasoning", encrypted_content="fixture")
        call = function_call("search_billing_documentation", json.dumps({"query": query}))

        async def model(**request):
            requests.append(list(request["input"]))
            assert request["model"] == "gpt-6-luna"
            assert request["store"] is False
            assert [tool["name"] for tool in request["tools"]] == [
                "search_billing_documentation"
            ]
            if len(requests) == 1:
                return response(reasoning_item, call)

            assert request["input"][1:3] == [reasoning_item, call]
            output = request["input"][-1]
            assert output["type"] == "function_call_output"
            assert output["call_id"] == "call_guide"
            payload = json.loads(output["output"])
            assert any(passage["section"] == "3.2" for passage in payload["passages"])
            return response(text="Ek 10 GB bloğu $10. [§3.2]")

        app = create_app()
        url = "http://127.0.0.1:8001/mcp"
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, trust_env=False) as http:
                async with Client(streamable_http_client(url, http_client=http)) as mcp:
                    result = await ask_billing_guide(
                        "Ek internet kaç dolar?", create_response=model, mcp_client=mcp
                    )

        assert result.answer == "Ek 10 GB bloğu $10. [§3.2]"
        assert len(requests) == 2
        assert result.tool_trace[0].name == "search_billing_documentation"
        assert result.tool_trace[0].arguments == {"query": query}
        assert result.tool_trace[0].result["document_id"] == "MOB-BILLING-2026-01"

    asyncio.run(check())


@pytest.mark.parametrize(
    ("name", "arguments"),
    [("pay_bill", "{}"), ("search_billing_documentation", '{"query": " "}')],
)
def test_agent_rejects_unsupported_or_invalid_tool_calls(name, arguments):
    from agent.billing_agent import ask_billing_guide

    class NoToolCalls:
        async def call_tool(self, *_args, **_kwargs):
            pytest.fail("Rejected tool requests must stay inside the Agent")

    async def check():
        async def model(**request):
            if len(request["input"]) == 1:
                return response(function_call(name, arguments))
            output = request["input"][-1]
            assert "error" in json.loads(output["output"])
            return response(text="Bu araç isteğini işleyemedim.")

        result = await ask_billing_guide(
            "Faturalama hakkında yardım", create_response=model, mcp_client=NoToolCalls()
        )
        assert result.answer == "Bu araç isteğini işleyemedim."
        assert "error" in result.tool_trace[0].result

    asyncio.run(check())


def test_agent_rest_only_returns_october_bill():
    from agent.billing_agent import ask_billing_guide
    from agent.billing_client import BillingClient

    class NoMcpCalls:
        async def call_tool(self, *_args, **_kwargs):
            pytest.fail("A REST-only question must not call MCP")

    async def model(**request):
        if len(request["input"]) == 1:
            assert [tool["name"] for tool in request["tools"]] == [
                "search_billing_documentation", "query_bill", "query_bill_details",
            ]
            return response(
                function_call(
                    "query_bill",
                    '{"year": 2026, "month": 10}',
                    call_id="call_october_bill",
                )
            )

        tool_output = request["input"][-1]
        assert tool_output["type"] == "function_call_output"
        assert tool_output["call_id"] == "call_october_bill"
        bill = json.loads(tool_output["output"])
        assert bill.get("total") == "80.00", bill

        return response(text="Ekim 2026 faturan $80.00.")

    async def check():
        token = jwt.encode(
            {
                "sub": "A001",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            "test-only-rest-agent-signing-key",
            algorithm="HS256",
        )
        requests = []

        def billing_api(request):
            requests.append(request)
            assert request.method == "GET"
            assert request.url.path == "/api/v1/subscribers/A001/bills/2026/10"
            assert request.headers["Authorization"] == f"Bearer {token}"
            return httpx2.Response(
                200,
                json={
                    "total": "80.00",
                    "paidAmount": "0.00",
                    "remainingBalance": "80.00",
                    "status": "unpaid",
                },
            )

        async with httpx2.AsyncClient(
            base_url="http://billing.test",
            transport=httpx2.MockTransport(billing_api),
        ) as http:
            result = await ask_billing_guide(
                "Ekim 2026 faturam ne kadar?",
                create_response=model,
                mcp_client=NoMcpCalls(),
                billing_client=BillingClient(http, "A001", token),
            )

        assert len(requests) == 1
        assert result.answer == "Ekim 2026 faturan $80.00."
        assert [call.name for call in result.tool_trace] == ["query_bill"]

    asyncio.run(check())


def test_agent_rest_and_mcp_explain_october_internet_charge(monkeypatch):
    from agent.billing_agent import ask_billing_guide
    from agent.billing_client import BillingClient
    from billing_api.main import app as billing_app
    from billing_api.routers import bills

    signing_key = "test-only-rest-and-mcp-signing-key"
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
    expected_answer = "35 GB kullandın: $50 taban ücret ve iki ek blok için $20. [§3.2]"

    async def model(**request):
        last_item = request["input"][-1]
        if last_item.get("role") == "user":
            return response(function_call(
                "query_bill_details", '{"year": 2026, "month": 10}', "call_details"
            ))

        assert last_item["type"] == "function_call_output"
        result = json.loads(last_item["output"])
        if last_item["call_id"] == "call_details":
            assert "error" not in result, result
            assert "subscriberNo" not in result
            assert result["internetMb"] == 35000
            assert {"type": "internet", "amount": "70.00"} in result["chargeBreakdown"]
            assert any(tool["name"] == "query_bill_details" for tool in request["tools"])
            return response(function_call(
                "search_billing_documentation",
                '{"query": "extra internet cost beyond 20 GB"}',
                "call_policy",
            ))

        assert last_item["call_id"] == "call_policy"
        assert any(passage["section"] == "3.2" for passage in result["passages"])
        return response(text=expected_answer)

    async def check():
        mcp_app = create_app()
        mcp_url = "http://127.0.0.1:8001/mcp"
        async with mcp_app.router.lifespan_context(mcp_app):
            async with (
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=billing_app),
                    base_url="http://billing.test",
                ) as billing_http,
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=mcp_app), trust_env=False,
                ) as mcp_http,
                Client(streamable_http_client(mcp_url, http_client=mcp_http)) as mcp,
            ):
                result = await ask_billing_guide(
                    "Ekim 2026'da internet ücretim neden $70?",
                    create_response=model,
                    mcp_client=mcp,
                    billing_client=BillingClient(billing_http, "A001", token),
                )

        assert bill_reads == [("A001", 2026, 10)]
        assert [call.name for call in result.tool_trace] == [
            "query_bill_details", "search_billing_documentation",
        ]
        assert result.answer == expected_answer

    asyncio.run(check())
