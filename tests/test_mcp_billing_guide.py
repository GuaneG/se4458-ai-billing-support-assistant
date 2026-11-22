import asyncio
from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def billing_client():
    from mcp_server.server import create_app

    app = create_app()
    url = "http://127.0.0.1:8001/mcp"
    transport = httpx2.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=transport, trust_env=False) as http:
            async with Client(streamable_http_client(url, http_client=http)) as client:
                yield client


@pytest.mark.parametrize(
    ("query", "section", "expected_excerpt"),
    [
        ("How much does extra internet cost beyond 20 GB?", "3.2", "10 GB block"),
        ("internet", "3.1", "20 GB"),
        ("Can I make a partial payment?", "5.1", "partial payment"),
        (
            "When can my service be restricted after the due date?",
            "6.3",
            "30 days after the due date",
        ),
    ],
)
def test_mcp_search_returns_the_relevant_billing_section(query, section, expected_excerpt):
    async def check():
        async with billing_client() as client:
            tools = (await client.list_tools()).tools
            assert [tool.name for tool in tools] == ["search_billing_documentation"]
            assert tools[0].input_schema["required"] == ["query"]

            result = await client.call_tool(
                "search_billing_documentation", {"query": query}
            )
            assert not result.is_error
            payload = result.structured_content
            assert payload["document_id"] == "MOB-BILLING-2026-01"
            assert 1 <= len(payload["passages"]) <= 3
            match = next(
                passage for passage in payload["passages"] if passage["section"] == section
            )
            assert match["heading"]
            assert expected_excerpt in match["excerpt"]

    asyncio.run(check())


@pytest.mark.parametrize(
    "query",
    ["zebrafish astronomy", "Can I use my internet package abroad while roaming?"],
    ids=["unrelated", "shared-internet-term"],
)
def test_mcp_search_returns_no_passages_for_insufficient_overlap(query):
    async def check():
        async with billing_client() as client:
            result = await client.call_tool(
                "search_billing_documentation", {"query": query}
            )
            assert not result.is_error
            assert result.structured_content["passages"] == []

    asyncio.run(check())
