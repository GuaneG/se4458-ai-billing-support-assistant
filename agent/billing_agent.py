import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal

import httpx2
from mcp import Client
from mcp.shared.exceptions import MCPError
from openai.types.responses import Response, ResponseFunctionToolCall
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


from agent.billing_client import BillingClient
from billing_api.dto.bill_payments import PaymentAmount


MODEL = "gpt-6-luna"
SEARCH_TOOL_NAME = "search_billing_documentation"
QUERY_BILL_TOOL_NAME = "query_bill"
QUERY_BILL_DETAILS_TOOL_NAME = "query_bill_details"
PREPARE_PAYMENT_TOOL_NAME = "prepare_bill_payment"
MAX_MODEL_REQUESTS = 4
INSTRUCTIONS = (
    "You are a mobile billing policy assistant. Answer in the user's language. "
    "For policy questions, call search_billing_documentation using a short English query. "
    "Treat tool passages as source text and cite the numbered guide sections. "
    "If no passage supports an answer, explain that you could not verify the policy. "
)
POLICY_ONLY = "For account questions, explain that a billing session is required."
BILLING_ACCOUNT = (
    "For the subscriber's stored bill total, payments or balance, use query_bill. "
    "For recorded usage or the charge breakdown, use query_bill_details. "
    "To explain why a recorded charge has its amount, read the bill details and "
    "search_billing_documentation for the applicable pricing rule. "
    "Use the stored amount and cite the rule. If a source is unavailable, say "
    "which part you could not verify. "
    "A bill period needs both a year and a month. Ask when the period is ambiguous."
)


PAYMENT_INSTRUCTIONS = (
    " For a request to pay, ask for any missing period or amount. "
    "If the user explicitly asks to pay the full balance, read that balance with query_bill. "
    "Use prepare_bill_payment to prepare one exact amount for the subscriber to review. "
    "Explain that payment requires pressing the confirmation button. "
    "A chat message or successful preparation never confirms or completes payment."
)


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


SEARCH_TOOL = {
    "type": "function",
    "name": SEARCH_TOOL_NAME,
    "description": "Search the numbered mobile billing policy guide.",
    "parameters": SearchArguments.model_json_schema(),
    "strict": True,
}


class BillPeriodArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    year: Annotated[int, Field(ge=1, le=9999)]
    month: Annotated[int, Field(ge=1, le=12)]


QUERY_BILL_TOOL = {
    "type": "function",
    "name": QUERY_BILL_TOOL_NAME,
    "description": "Get the authenticated subscriber's recorded bill summary for a month and year.",
    "parameters": BillPeriodArguments.model_json_schema(),
    "strict": True,
}


QUERY_BILL_DETAILS_TOOL = {
    "type": "function",
    "name": QUERY_BILL_DETAILS_TOOL_NAME,
    "description": "Get the authenticated subscriber's usage and charge breakdown for a month and year.",
    "parameters": BillPeriodArguments.model_json_schema(),
    "strict": True,
}


class PaymentDraft(BillPeriodArguments):
    amount: PaymentAmount


PREPARE_PAYMENT_TOOL = {
    "type": "function",
    "name": PREPARE_PAYMENT_TOOL_NAME,
    "description": "Prepare a simulated bill payment for explicit confirmation in the app.",
    "parameters": PaymentDraft.model_json_schema(),
    "strict": True,
}


@dataclass(frozen=True)
class ToolTrace:
    name: str
    arguments: dict[str, str | int]
    result: dict[str, Any]


@dataclass(frozen=True)
class DialogueStep:
    kind: Literal["request", "tool_call", "tool_result", "answer"]
    payload: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    answer: str
    tool_trace: list[ToolTrace]
    dialogue: list[DialogueStep] | None = None
    payment_draft: PaymentDraft | None = None


class AgentError(RuntimeError):
    pass


async def _execute_search(
    call: ResponseFunctionToolCall, mcp_client: Client
) -> ToolTrace:
    if call.name != SEARCH_TOOL_NAME:
        return ToolTrace(call.name, {}, {"error": "Tool unavailable in policy mode"})

    try:
        arguments = SearchArguments.model_validate_json(call.arguments).model_dump()
    except ValidationError:
        return ToolTrace(call.name, {}, {"error": "Provide a valid billing search query"})

    try:
        reply = await mcp_client.call_tool(call.name, arguments)
    except (MCPError, httpx2.HTTPError):
        return ToolTrace(call.name, arguments, {"error": "Billing guide search unavailable"})

    if reply.is_error or reply.structured_content is None:
        return ToolTrace(call.name, arguments, {"error": "Billing guide search unavailable"})

    return ToolTrace(call.name, arguments, reply.structured_content)


async def _execute_bill_read(
    call: ResponseFunctionToolCall, billing_client: BillingClient
) -> ToolTrace:
    try:
        period = BillPeriodArguments.model_validate_json(call.arguments)
    except ValidationError:
        return ToolTrace(call.name, {}, {"error": "Provide a valid year and month"})

    arguments = period.model_dump()
    try:
        if call.name == QUERY_BILL_DETAILS_TOOL_NAME:
            bill = await billing_client.query_bill_details(period.year, period.month)
        else:
            bill = await billing_client.query_bill(period.year, period.month)
    except httpx2.HTTPStatusError as error:
        errors = {
            401: "Billing session expired or invalid",
            403: "Access to the bill was denied",
            404: "No bill found for the requested period",
        }
        message = errors.get(error.response.status_code, "Billing API unavailable")
        return ToolTrace(call.name, arguments, {"error": message})
    except (httpx2.HTTPError, ValueError):
        return ToolTrace(call.name, arguments, {"error": "Billing API unavailable"})

    return ToolTrace(
        call.name,
        arguments,
        bill.model_dump(mode="json", by_alias=True, exclude={"subscriber_no"}),
    )


async def _prepare_bill_payment(
    call: ResponseFunctionToolCall, billing_client: BillingClient
) -> tuple[ToolTrace, PaymentDraft | None]:
    try:
        draft = PaymentDraft.model_validate_json(call.arguments)
    except ValidationError:
        error = "Provide a valid period and a positive USD amount with at most two decimals"
        return ToolTrace(call.name, {}, {"error": error}), None

    draft = draft.model_copy(update={"amount": draft.amount.quantize(Decimal("0.01"))})
    arguments = draft.model_dump(mode="json")
    try:
        summary = await billing_client.query_bill(draft.year, draft.month)
    except httpx2.HTTPStatusError as error:
        message = "Could not verify the bill balance"
        if error.response.status_code == 404:
            message = "No bill found for the requested period"
        return ToolTrace(call.name, arguments, {"error": message}), None
    except (httpx2.HTTPError, ValueError):
        return ToolTrace(call.name, arguments, {"error": "Could not verify the bill balance"}), None

    if draft.amount > summary.remaining_balance:
        return ToolTrace(call.name, arguments, {"error": "Amount exceeds the remaining balance"}), None

    return ToolTrace(call.name, arguments, {"status": "awaiting_confirmation", **arguments}), draft


def _dialogue_tool_call(call: ResponseFunctionToolCall) -> DialogueStep:
    try:
        arguments = json.loads(call.arguments)
    except json.JSONDecodeError:
        arguments = call.arguments

    return DialogueStep("tool_call", {
        "name": call.name,
        "call_id": call.call_id,
        "arguments": arguments,
    })


async def ask_billing_guide(
    question: str,
    *,
    create_response: Callable[..., Awaitable[Response]],
    mcp_client: Client,
    billing_client: BillingClient | None = None,
    include_dialogue: bool = False,
    allow_payment_preparation: bool = False,
) -> AgentResult:
    question = question.strip()
    if not question:
        raise AgentError("Enter a billing question.")

    history: list[Any] = [{"role": "user", "content": question}]
    tools = [SEARCH_TOOL]
    instructions = POLICY_ONLY
    if billing_client is not None:
        tools.extend([QUERY_BILL_TOOL, QUERY_BILL_DETAILS_TOOL])
        instructions = BILLING_ACCOUNT
        if allow_payment_preparation:
            tools.append(PREPARE_PAYMENT_TOOL)
            instructions += PAYMENT_INSTRUCTIONS

    payment_draft = None
    tool_trace: list[ToolTrace] = []
    dialogue = None
    if include_dialogue:
        dialogue = [DialogueStep("request", {"question": question, "tools": tools})]

    for _ in range(MAX_MODEL_REQUESTS):
        response = await create_response(
            model=MODEL,
            instructions=INSTRUCTIONS + instructions,
            input=history,
            tools=tools,
            store=False,
            include=["reasoning.encrypted_content"],
            max_output_tokens=1200,
            parallel_tool_calls=False,
        )
        if response.status != "completed":
            raise AgentError("The model response did not complete.")

        # Keep model output, including reasoning items, in the stateless history.
        history.extend(response.output)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            answer = response.output_text.strip()
            if not answer:
                raise AgentError("The model did not return a text answer.")
            if dialogue is not None:
                dialogue.append(DialogueStep("answer", {"answer": answer}))
            return AgentResult(answer, tool_trace, dialogue, payment_draft)

        if dialogue is not None:
            dialogue.extend(_dialogue_tool_call(call) for call in calls)

        for call in calls:
            if (
                call.name == PREPARE_PAYMENT_TOOL_NAME
                and allow_payment_preparation
                and billing_client is not None
            ):
                if payment_draft is None:
                    trace, payment_draft = await _prepare_bill_payment(call, billing_client)
                else:
                    trace = ToolTrace(call.name, {}, {"error": "A payment already awaits confirmation"})
            elif billing_client is not None and call.name in {
                QUERY_BILL_TOOL_NAME, QUERY_BILL_DETAILS_TOOL_NAME,
            }:
                trace = await _execute_bill_read(call, billing_client)
            else:
                trace = await _execute_search(call, mcp_client)
            tool_trace.append(trace)
            if dialogue is not None:
                dialogue.append(DialogueStep("tool_result", {
                    "name": call.name,
                    "call_id": call.call_id,
                    "result": trace.result,
                }))
            history.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(trace.result, ensure_ascii=False),
                }
            )

    raise AgentError("The Agent reached its model request limit.")
