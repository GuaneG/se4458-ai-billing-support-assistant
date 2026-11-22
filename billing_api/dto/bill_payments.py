from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel


class BillSummary(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    total: Decimal
    paid_amount: Decimal
    remaining_balance: Decimal
    status: Literal["unpaid", "paid"]


PaymentAmount = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class PaymentRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid")

    amount: PaymentAmount
    transaction_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]


class PaymentResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    status: Literal["success"] = "success"
    paid_amount: Decimal
    remaining_balance: Decimal
