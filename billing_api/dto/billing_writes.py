from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BillingPeriod(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid")

    subscriber_no: Annotated[str, Field(min_length=1)]
    year: Annotated[int, Field(ge=1, le=9999)]
    month: Annotated[int, Field(ge=1, le=12)]


class UsageEvent(BillingPeriod):
    usage_type: Literal["Phone", "Internet"]


class TransactionStatus(BaseModel):
    status: Literal["success"] = "success"
