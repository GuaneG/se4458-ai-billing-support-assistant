from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import httpx2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field

from billing_api.dto.billing_writes import BillingPeriod, TransactionStatus, UsageEvent
from billing_api.routers.bills import bearer_scheme, require_billing_writer, require_claims


APPROVAL_TTL_SECONDS = 5 * 60
BILLING_ROUTES = {"add_usage": "api/v1/usage", "calculate_bill": "api/v1/bills/calculate"}


class AddUsageOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["add_usage"]
    billing: UsageEvent


class CalculateBillOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["calculate_bill"]
    billing: BillingPeriod


Operation = Annotated[AddUsageOperation | CalculateBillOperation, Field(discriminator="kind")]


class PendingOperation(BaseModel):
    confirmation_id: UUID
    operation: Operation


class ConfirmOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: UUID


@dataclass
class _Approval:
    operator: str
    operation: Operation
    expires_at: float
    used: bool = False


def create_operator_router(http_client: Callable[[], httpx2.AsyncClient]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/operator/operations", tags=["Operator"])
    approvals: dict[UUID, _Approval] = {}
    lock = Lock()

    @router.post("/prepare", dependencies=[Depends(require_billing_writer)])
    async def prepare(
        operation: Operation,
        claims: Annotated[dict[str, Any], Depends(require_claims)],
    ) -> PendingOperation:
        confirmation_id = uuid4()
        now = monotonic()
        with lock:
            expired = [key for key, approval in approvals.items() if approval.expires_at <= now]
            for key in expired:
                del approvals[key]
            approvals[confirmation_id] = _Approval(
                claims["sub"], operation, now + APPROVAL_TTL_SECONDS,
            )

        return PendingOperation(confirmation_id=confirmation_id, operation=operation)

    @router.post("/confirm", dependencies=[Depends(require_billing_writer)])
    async def confirm(
        payload: ConfirmOperationRequest,
        claims: Annotated[dict[str, Any], Depends(require_claims)],
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    ) -> TransactionStatus:
        with lock:
            approval = approvals.get(payload.confirmation_id)
            if (
                approval is None
                or approval.operator != claims["sub"]
                or approval.expires_at <= monotonic()
            ):
                raise HTTPException(404, "Operation confirmation not found or expired")
            if approval.used:
                raise HTTPException(409, "Operation confirmation already used")

            # Add Usage may have committed even when its HTTP response is lost.
            approval.used = True

        try:
            async with http_client() as http:
                response = await http.post(
                    BILLING_ROUTES[approval.operation.kind],
                    headers={"Authorization": f"Bearer {credentials.credentials}"},
                    json=approval.operation.billing.model_dump(mode="json", by_alias=True),
                    follow_redirects=False,
                )
                response.raise_for_status()
                return TransactionStatus.model_validate(response.json())
        except httpx2.HTTPStatusError as error:
            code = error.response.status_code
            if code == 404:
                raise HTTPException(404, "Subscriber not found") from None
            if code in {401, 403, 422}:
                raise HTTPException(code, "Billing rejected the operation") from None
            raise HTTPException(502, "Billing could not confirm the operation result") from None
        except (httpx2.HTTPError, ValueError):
            raise HTTPException(502, "Billing could not confirm the operation result") from None

    return router
