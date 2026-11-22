import argparse
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from getpass import getpass
from os import environ, getenv
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx2
import uvicorn
from dotenv import dotenv_values
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent.billing_agent import (
    PREPARE_PAYMENT_TOOL_NAME,
    QUERY_BILL_DETAILS_TOOL_NAME,
    QUERY_BILL_TOOL_NAME,
    SEARCH_TOOL_NAME,
)
from agent.chat_api import create_app
from billing_api.main import app as billing_app
from mcp_server.server import create_app as create_mcp_app


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
GUIDE_QUESTION = "Ek internet kaç dolar?"
SUMMARY_QUESTION = "Ekim 2026 faturam ne kadar?"
DETAILS_QUESTION = "Ekim 2026'da internet ücretim neden $70?"
PAYMENT_QUESTION = "Ekim 2026 faturama $20 öde."
EXAMPLES = (
    {"source": "MCP", "question": GUIDE_QUESTION},
    {"source": "REST", "question": SUMMARY_QUESTION},
    {"source": "REST + MCP", "question": DETAILS_QUESTION},
    {"source": "Ödeme", "question": PAYMENT_QUESTION},
)
GUIDE_QUERY = {"query": "extra internet cost beyond 20 GB"}
PERIOD = {"year": 2026, "month": 10}


def tool_request(name, arguments):
    return SimpleNamespace(
        status="completed",
        output=[SimpleNamespace(
            type="function_call", name=name, call_id=f"demo_{name}",
            arguments=json.dumps(arguments),
        )],
    )


def answer(text):
    return SimpleNamespace(status="completed", output=[], output_text=text)


async def scripted_response(**request):
    history = request["input"]
    question = history[0]["content"]
    if len(history) == 1:
        if question == GUIDE_QUESTION:
            return tool_request(SEARCH_TOOL_NAME, GUIDE_QUERY)
        if question == SUMMARY_QUESTION:
            return tool_request(QUERY_BILL_TOOL_NAME, PERIOD)
        if question == DETAILS_QUESTION:
            return tool_request(QUERY_BILL_DETAILS_TOOL_NAME, PERIOD)
        if question == PAYMENT_QUESTION:
            return tool_request(PREPARE_PAYMENT_TOOL_NAME, {**PERIOD, "amount": "20.00"})
        return answer("Yerel demo için yukarıdaki örnek sorulardan birini seç.")

    result = json.loads(history[-1]["output"])
    if question == PAYMENT_QUESTION:
        if result.get("status") != "awaiting_confirmation":
            return answer("Ödeme taslağı hazırlanamadı. Kalan bakiyeni kontrol et.")
        return answer("Ödeme hazır. Dönemi ve tutarı kontrol edip onaylayabilirsin.")

    if "error" in result:
        return answer("Kaynağı okuyamadım. Yerel servisleri kontrol edip tekrar dene.")

    if question == SUMMARY_QUESTION:
        return answer(
            f"Ekim 2026 faturan ${result['total']}. Kalan bakiyen ${result['remainingBalance']}."
        )

    if history[-1]["call_id"] == f"demo_{QUERY_BILL_DETAILS_TOOL_NAME}":
        return tool_request(SEARCH_TOOL_NAME, GUIDE_QUERY)

    passage = next((item for item in result["passages"] if item["section"] == "3.2"), None)
    if passage is None:
        return answer("Ek internet ücretine ait rehber bölümünü bulamadım.")

    excerpt = passage["excerpt"].replace("**", "")

    if question == GUIDE_QUESTION:
        return answer(f"Rehberin ek internet kuralı [§{passage['section']}]\n\n{excerpt}")

    details = json.loads(history[-3]["output"])
    charge = next(line["amount"] for line in details["chargeBreakdown"] if line["type"] == "internet")
    usage = format(Decimal(details["internetGb"]).normalize(), "f")
    explanation = f"Ekim faturanda {usage} GB internet kullanımı ve ${charge} internet ücreti var."
    if usage == "35" and Decimal(charge) == Decimal("70"):
        explanation += "\n\nPaketin ilk 20 GB'ı $50. Kalan 15 GB iki adet $10'lık bloğa giriyor. [§3.2]"
    else:
        explanation += f"\n\n{excerpt} [§{passage['section']}]"
    return answer(explanation)


def create_demo_app(*, demo_password: str, live: bool = False):
    mcp_app = create_mcp_app()

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = create_app(
        create_response=None if live else scripted_response,
        billing_transport=httpx2.ASGITransport(app=billing_app),
        mcp_transport=httpx2.ASGITransport(app=mcp_app),
        lifespan=lifespan,
        include_dialogue=True,
        demo_password=demo_password,
        examples=EXAMPLES,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    return app


def main():
    parser = argparse.ArgumentParser(description="Run the local Billing Support Chat")
    parser.add_argument("--live", action="store_true", help="Send Chat questions to the OpenAI API")
    args = parser.parse_args()

    settings = dotenv_values(ENV_PATH)
    if args.live:
        api_key = getenv("OPENAI_API_KEY") or settings.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("Set OPENAI_API_KEY in the project's .env before starting live mode.")
        environ["OPENAI_API_KEY"] = api_key

    db_url = getenv("BILLING_DATABASE_URL") or settings.get("BILLING_DATABASE_URL")
    parsed = urlsplit(db_url or "")
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/billing_dev":
        raise SystemExit("Set BILLING_DATABASE_URL to the local billing_dev database.")
    demo_password = getenv("DEMO_LOGIN_PASSWORD") or settings.get("DEMO_LOGIN_PASSWORD")
    if not demo_password:
        demo_password = getpass("A001 için demo şifresi belirle: ")
    if not 1 <= len(demo_password) <= 256:
        raise SystemExit("Enter a demo password between 1 and 256 characters.")

    signing_key = token_hex(32)
    environ["BILLING_DATABASE_URL"] = db_url
    environ["BILLING_JWT_SECRET"] = signing_key
    environ["BILLING_API_BASE_URL"] = "http://127.0.0.1:8000"
    environ["MCP_URL"] = "http://127.0.0.1:8001/mcp"
    app = create_demo_app(demo_password=demo_password, live=args.live)
    uvicorn.run(app, host="127.0.0.1", port=8002)


if __name__ == "__main__":
    main()
