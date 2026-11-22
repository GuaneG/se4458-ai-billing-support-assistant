import argparse
import asyncio
import json
from dataclasses import asdict
from os import getenv
from pathlib import Path
from sys import stderr
from types import SimpleNamespace

import httpx2
from dotenv import load_dotenv
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from openai import AsyncOpenAI, OpenAIError

from agent.billing_agent import AgentError, AgentResult, SEARCH_TOOL_NAME, ask_billing_guide


DEMO_QUESTION = "Ek internet kaç dolar?"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


async def demo_response(**request):
    history = request["input"]
    if len(history) == 1:
        call = SimpleNamespace(
            type="function_call",
            call_id="call_offline_guide",
            name=SEARCH_TOOL_NAME,
            arguments=json.dumps({"query": "extra internet cost beyond 20 GB"}),
        )
        return SimpleNamespace(status="completed", output=[call], output_text="")

    result = json.loads(history[-1]["output"])
    passages = result.get("passages", [])
    passage = next((item for item in passages if item["section"] == "3.2"), None)
    if passage is None:
        raise AgentError("The demo did not find the extra internet pricing section.")

    answer = f"{passage['excerpt']} [{result['document_id']} §{passage['section']}]"
    return SimpleNamespace(status="completed", output=[], output_text=answer)


async def run(args: argparse.Namespace) -> AgentResult:
    async with httpx2.AsyncClient(timeout=8, trust_env=False) as http:
        transport = streamable_http_client(args.mcp_url, http_client=http)
        async with Client(transport) as mcp_client:
            if args.offline_demo:
                return await ask_billing_guide(
                    DEMO_QUESTION, create_response=demo_response, mcp_client=mcp_client
                )

            load_dotenv(ENV_PATH)
            api_key = getenv("OPENAI_API_KEY")
            if not api_key:
                raise AgentError("Set OPENAI_API_KEY in the project's .env.")
            async with AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.openai.com/v1",
                timeout=20,
                max_retries=0,
            ) as openai:
                return await ask_billing_guide(
                    args.live, create_response=openai.responses.create, mcp_client=mcp_client
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="SE4458 billing policy Agent")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--offline-demo", action="store_true", help="Scripted model with real MCP")
    modes.add_argument("--live", metavar="QUESTION", help="Send a question to OpenAI")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8001/mcp")
    args = parser.parse_args()

    try:
        result = asyncio.run(run(args))
    except AgentError as error:
        print(error, file=stderr)
        return 1
    except (MCPError, httpx2.HTTPError) as error:
        print(f"MCP connection failed ({type(error).__name__}).", file=stderr)
        return 1
    except OpenAIError as error:
        print(f"OpenAI request failed ({type(error).__name__}).", file=stderr)
        return 1

    print("Offline demo" if args.offline_demo else "Live OpenAI")
    for call in result.tool_trace:
        print(json.dumps(asdict(call), ensure_ascii=True))
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
