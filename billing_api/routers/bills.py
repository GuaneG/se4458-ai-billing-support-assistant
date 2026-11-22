from decimal import Decimal
from os import getenv
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import OperationalError

from billing_api.db.bills import (
    DuplicateTransactionId,
    InsufficientBalance,
    find_bill,
    recalculate_bill,
    record_payment,
    record_usage,
)
from billing_api.dto.bill_details import BillDetails, ChargeLine
from billing_api.dto.bill_payments import BillSummary, PaymentRequest, PaymentResult
from billing_api.dto.billing_writes import BillingPeriod, TransactionStatus, UsageEvent


router = APIRouter(prefix="/api/v1", tags=["Billing"])
bearer_scheme = HTTPBearer(auto_error=False)


def require_claims(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> dict[str, Any]:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="A valid bearer token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    signing_key = getenv("BILLING_JWT_SECRET", "")
    if len(signing_key.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing authentication is not configured",
        )

    try:
        claims = jwt.decode(
            credentials.credentials,
            signing_key,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
    except jwt.InvalidTokenError as error:
        raise unauthorized from error

    return claims


def require_subscriber(claims: Annotated[dict[str, Any], Depends(require_claims)]) -> str:
    return claims["sub"]


def require_bill_owner(subscriber_no: str, authenticated_subscriber: str) -> None:
    if subscriber_no != authenticated_subscriber:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This bill belongs to another subscriber",
        )


async def optional_subscriber(request: Request) -> str | None:
    if "authorization" not in request.headers:
        return None
    return require_claims(await bearer_scheme(request))["sub"]


def require_billing_writer(
    claims: Annotated[dict[str, Any], Depends(require_claims)],
) -> None:
    scope = claims.get("scope")
    if not isinstance(scope, str) or "billing:write" not in scope.split():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Billing write permission is required",
        )


@router.get(
    "/subscribers/{subscriber_no}/bills/{year}/{month}/details",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "The token belongs to another subscriber"},
        404: {"description": "No bill found for the requested period"},
        503: {"description": "Billing database or authentication unavailable"},
    },
)
def get_bill_details(
    subscriber_no: str,
    year: Annotated[int, Path(ge=1)],
    month: Annotated[int, Path(ge=1, le=12)],
    authenticated_subscriber: Annotated[str, Depends(require_subscriber)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 10,
) -> BillDetails:
    require_bill_owner(subscriber_no, authenticated_subscriber)

    try:
        bill = find_bill(subscriber_no, year, month)
    except OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing database is unavailable",
        ) from error

    if bill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No bill found for the requested period",
        )

    phone_charge = Decimal(bill["phone_charge_cents"]).scaleb(-2)
    internet_charge = Decimal(bill["internet_charge_cents"]).scaleb(-2)
    paid_amount = Decimal(bill["paid_cents"]).scaleb(-2)
    total = phone_charge + internet_charge
    charges = [
        ChargeLine(type="phone", amount=phone_charge),
        ChargeLine(type="internet", amount=internet_charge),
    ]
    offset = (page - 1) * page_size

    return BillDetails(
        subscriber_no=subscriber_no,
        year=year,
        month=month,
        total=total,
        paid_amount=paid_amount,
        remaining_balance=total - paid_amount,
        phone_minutes=bill["phone_minutes"],
        internet_mb=bill["internet_mb"],
        internet_gb=Decimal(bill["internet_mb"]).scaleb(-3),
        charge_breakdown=charges[offset : offset + page_size],
        page=page,
        page_size=page_size,
        total_items=len(charges),
    )



WRITE_RESPONSES = {
    401: {"description": "Missing or invalid bearer token"},
    403: {"description": "Billing write permission is required"},
    404: {"description": "Subscriber not found"},
    503: {"description": "Billing database or authentication unavailable"},
}


@router.post(
    "/usage",
    dependencies=[Depends(require_billing_writer)],
    responses=WRITE_RESPONSES,
)
def add_usage(payload: UsageEvent) -> TransactionStatus:
    minutes, mb = (10, 0) if payload.usage_type == "Phone" else (0, 1)
    try:
        recorded = record_usage(
            payload.subscriber_no, payload.year, payload.month, minutes, mb
        )
    except OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing database is unavailable",
        ) from error

    if not recorded:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return TransactionStatus()


@router.post(
    "/bills/calculate",
    dependencies=[Depends(require_billing_writer)],
    responses=WRITE_RESPONSES,
)
def calculate_bill(payload: BillingPeriod) -> TransactionStatus:
    try:
        calculated = recalculate_bill(payload.subscriber_no, payload.year, payload.month)
    except OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing database is unavailable",
        ) from error

    if not calculated:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return TransactionStatus()


@router.get(
    "/subscribers/{subscriber_no}/bills/{year}/{month}",
    openapi_extra={"security": [{}, {"HTTPBearer": []}]},
    responses={
        401: {"description": "Invalid bearer token"},
        403: {"description": "The token belongs to another subscriber"},
        404: {"description": "No visible bill found for the requested period"},
        503: {"description": "Billing database or authentication unavailable"},
    },
)
def get_bill_summary(
    subscriber_no: str,
    year: Annotated[int, Path(ge=1)],
    month: Annotated[int, Path(ge=1, le=12)],
    authenticated_subscriber: Annotated[str | None, Depends(optional_subscriber)],
) -> BillSummary:
    if authenticated_subscriber is not None:
        require_bill_owner(subscriber_no, authenticated_subscriber)

    try:
        bill = find_bill(
            subscriber_no, year, month, public_only=authenticated_subscriber is None
        )
    except OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing database is unavailable",
        ) from error

    if bill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No bill found for the requested period",
        )

    total = Decimal(bill["phone_charge_cents"] + bill["internet_charge_cents"]).scaleb(-2)
    paid_amount = Decimal(bill["paid_cents"]).scaleb(-2)
    remaining_balance = total - paid_amount
    return BillSummary(
        total=total,
        paid_amount=paid_amount,
        remaining_balance=remaining_balance,
        status="paid" if remaining_balance == 0 else "unpaid",
    )


@router.post(
    "/subscribers/{subscriber_no}/bills/{year}/{month}/payments",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "The token belongs to another subscriber"},
        404: {"description": "No bill found for the requested period"},
        409: {"description": "Duplicate transaction ID or payment exceeds the balance"},
        503: {"description": "Billing database or authentication unavailable"},
    },
)
def pay_bill(
    subscriber_no: str,
    year: Annotated[int, Path(ge=1)],
    month: Annotated[int, Path(ge=1, le=12)],
    payload: PaymentRequest,
    authenticated_subscriber: Annotated[str, Depends(require_subscriber)],
) -> PaymentResult:
    require_bill_owner(subscriber_no, authenticated_subscriber)

    amount_cents = int(payload.amount.scaleb(2))
    try:
        balance_cents = record_payment(
            subscriber_no, year, month, payload.transaction_id, amount_cents
        )
    except DuplicateTransactionId as error:
        raise HTTPException(status_code=409, detail="Transaction ID already exists") from error
    except InsufficientBalance as error:
        raise HTTPException(
            status_code=409, detail="Amount exceeds the remaining balance"
        ) from error
    except OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing database is unavailable",
        ) from error

    if balance_cents is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No bill found for the requested period",
        )

    return PaymentResult(
        paid_amount=Decimal(amount_cents).scaleb(-2),
        remaining_balance=Decimal(balance_cents).scaleb(-2),
    )
