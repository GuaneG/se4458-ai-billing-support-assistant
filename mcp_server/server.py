from pathlib import Path
from typing import Annotated

import uvicorn
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import StringConstraints
from starlette.applications import Starlette

from mcp_server.billing_guide import BillingGuideIndex, SearchResult


GUIDE_PATH = Path(__file__).with_name("Mobile_Provider_Billing_Guide.md")
guide_index = BillingGuideIndex.load(GUIDE_PATH)


def search_billing_documentation(
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)],
) -> SearchResult:
    """Find general mobile billing rules by keyword and return numbered guide excerpts."""
    return guide_index.search(query)


def create_app() -> Starlette:
    server = MCPServer("SE4458 Billing Guide")
    server.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )(search_billing_documentation)
    return server.streamable_http_app(stateless_http=True, json_response=True)


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
