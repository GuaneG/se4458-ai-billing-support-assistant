from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from os import getenv
from pathlib import Path
from secrets import token_bytes
from typing import Annotated
from uuid import UUID, uuid4

import httpx2
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from openai import (
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.responses import Response
from psycopg import OperationalError
from pydantic import BaseModel, ConfigDict, SecretStr, StringConstraints

from agent.billing_agent import AgentError, DialogueStep, ToolTrace, ask_billing_guide
from agent.billing_client import BillingClient
from agent.operator_accounts import find_operator_credentials, password_digest
from agent.operator_api import create_operator_router
from agent.payment_approvals import PaymentApprovals, PendingPayment
from billing_api.dto.bill_payments import PaymentResult
from billing_api.routers.bills import bearer_scheme, require_subscriber


WEB_DIR = Path(__file__).with_name("web")
DEMO_SUBSCRIBER = "A001"
LOGIN_PATH = "/api/v1/auth/login"
SESSION_LIFETIME = timedelta(minutes=15)


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, StringConstraints(strip_whitespace=True)]
    password: SecretStr


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatResponse(BaseModel):
    answer: str
    tool_trace: list[ToolTrace]
    dialogue: list[DialogueStep] | None = None
    pending_payment: PendingPayment | None = None


class ConfirmPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: UUID


def create_app(
    *,
    create_response: Callable[..., Awaitable[Response]] | None = None,
    billing_transport: httpx2.AsyncBaseTransport | None = None,
    mcp_transport: httpx2.AsyncBaseTransport | None = None,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    include_dialogue: bool = False,
    demo_password: str | None = None,
    examples: tuple[dict[str, str], ...] = (),
) -> FastAPI:
    app = FastAPI(title="Billing Support Chat", lifespan=lifespan)
    approvals = PaymentApprovals()
    salt = token_bytes(16)
    expected_password = password_digest(demo_password, salt) if demo_password else None
    dummy_password = bytes(64)

    app.mount("/chat-assets", StaticFiles(directory=WEB_DIR), name="chat-assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if request.url.path == LOGIN_PATH:
            return JSONResponse(
                {"detail": "Invalid demo credential format"},
                status_code=422,
                headers={"Cache-Control": "no-store"},
            )
        return await request_validation_exception_handler(request, error)

    @app.post(LOGIN_PATH)
    def login(payload: DemoLoginRequest) -> JSONResponse:
        signing_key = getenv("BILLING_JWT_SECRET", "")
        if len(signing_key.encode("utf-8")) < 32:
            raise HTTPException(503, "Demo login is not configured")

        password = payload.password.get_secret_value()
        if len(password) > 256:
            raise HTTPException(401, "Invalid demo credentials")

        if payload.username == DEMO_SUBSCRIBER:
            if expected_password is None:
                raise HTTPException(503, "Demo login is not configured")
            role = "subscriber"
            subject = DEMO_SUBSCRIBER
            stored_salt, stored_password = salt, expected_password
            exists = True
        else:
            role = "operator"
            username = payload.username.lower()
            subject = f"operator:{username}"
            try:
                stored = find_operator_credentials(username)
            except OperationalError:
                raise HTTPException(503, "Operator login is unavailable") from None
            stored_salt, stored_password = stored or (salt, dummy_password)
            exists = stored is not None

        password_valid = compare_digest(password_digest(password, stored_salt), stored_password)
        if not exists or not password_valid:
            raise HTTPException(401, "Invalid demo credentials")

        claims = {
            "sub": subject,
            "exp": datetime.now(timezone.utc) + SESSION_LIFETIME,
            "jti": uuid4().hex,
        }
        if role == "operator":
            claims["scope"] = "billing:write"

        token = jwt.encode(claims, signing_key, algorithm="HS256")
        return JSONResponse(
            {
                "token": token,
                "examples": examples if role == "subscriber" else (),
                "mode": "live" if create_response is None else "demo",
                "role": role,
            },
            headers={"Cache-Control": "no-store"},
        )

    def billing_http_client() -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            base_url=getenv("BILLING_API_BASE_URL", "http://127.0.0.1:8000"),
            transport=billing_transport,
            timeout=8,
            trust_env=False,
        )

    app.include_router(create_operator_router(billing_http_client))

    @app.post("/api/v1/chat", response_model_exclude_none=True)
    async def chat(
        payload: ChatRequest,
        subscriber_no: Annotated[str, Depends(require_subscriber)],
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    ) -> ChatResponse:
        if subscriber_no.startswith("operator:"):
            raise HTTPException(403, "Use a subscriber account for billing chat")
        try:
            async with AsyncExitStack() as stack:
                response_creator = create_response
                if response_creator is None:
                    api_key = getenv("OPENAI_API_KEY")
                    if not api_key:
                        raise HTTPException(503, "Chat model is not configured.")
                    openai = await stack.enter_async_context(AsyncOpenAI(
                        api_key=api_key,
                        base_url="https://api.openai.com/v1",
                        timeout=20,
                        max_retries=0,
                    ))
                    response_creator = openai.responses.create

                billing_http = await stack.enter_async_context(billing_http_client())
                mcp_http = await stack.enter_async_context(httpx2.AsyncClient(
                    transport=mcp_transport,
                    timeout=8,
                    trust_env=False,
                ))
                mcp_url = getenv("MCP_URL", "http://127.0.0.1:8001/mcp")
                mcp = await stack.enter_async_context(
                    Client(streamable_http_client(mcp_url, http_client=mcp_http))
                )

                result = await ask_billing_guide(
                    payload.question,
                    create_response=response_creator,
                    mcp_client=mcp,
                    include_dialogue=include_dialogue,
                    allow_payment_preparation=True,
                    billing_client=BillingClient(
                        billing_http, subscriber_no, credentials.credentials,
                    ),
                )
                pending_payment = (
                    approvals.add(subscriber_no, result.payment_draft)
                    if result.payment_draft is not None
                    else None
                )
                return ChatResponse(
                    answer=result.answer,
                    tool_trace=result.tool_trace,
                    dialogue=result.dialogue,
                    pending_payment=pending_payment,
                )
        except* RateLimitError:
            raise HTTPException(
                429, "OpenAI API kotasını ve proje bakiyesini kontrol et."
            ) from None
        except* (AuthenticationError, PermissionDeniedError, NotFoundError):
            raise HTTPException(
                502, "OpenAI API erişimi başarısız. API anahtarını ve model erişimini kontrol et."
            ) from None
        except* (AgentError, MCPError, httpx2.HTTPError, OpenAIError):
            raise HTTPException(502, "A chat dependency could not complete the request.") from None

    @app.post("/api/v1/chat/payments/confirm")
    async def confirm_payment(
        payload: ConfirmPaymentRequest,
        subscriber_no: Annotated[str, Depends(require_subscriber)],
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    ) -> PaymentResult:
        with approvals.claim(payload.confirmation_id, subscriber_no) as payment:
            async with billing_http_client() as http:
                billing = BillingClient(http, subscriber_no, credentials.credentials)
                try:
                    return await billing.pay_bill(
                        payment.year,
                        payment.month,
                        amount=payment.amount,
                        transaction_id=str(payment.confirmation_id),
                    )
                except httpx2.HTTPStatusError as error:
                    errors = {
                        401: "Billing session expired or invalid",
                        403: "Access to the bill was denied",
                        404: "No bill found for the requested period",
                        409: "Payment already recorded or amount exceeds the remaining balance",
                    }
                    code = error.response.status_code
                    if code in errors:
                        raise HTTPException(code, errors[code]) from None
                    raise HTTPException(502, "Billing API unavailable") from None
                except (httpx2.HTTPError, ValueError):
                    raise HTTPException(502, "Billing API unavailable") from None

    return app


app = create_app(demo_password=getenv("DEMO_LOGIN_PASSWORD"))
