from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ChargeLine(BaseModel):
    type: Literal["phone", "internet"]
    amount: Decimal


class BillDetails(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    subscriber_no: str
    year: int
    month: int
    currency: Literal["USD"] = "USD"
    total: Decimal
    paid_amount: Decimal
    remaining_balance: Decimal
    phone_minutes: int
    internet_mb: int
    internet_gb: Decimal
    charge_breakdown: list[ChargeLine]
    page: int
    page_size: int
    total_items: int
