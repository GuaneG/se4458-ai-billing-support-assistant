from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import quote

import httpx2

from billing_api.dto.bill_details import BillDetails
from billing_api.dto.bill_payments import BillSummary, PaymentRequest, PaymentResult


@dataclass(frozen=True)
class BillingClient:
    http: httpx2.AsyncClient
    subscriber_no: str
    bearer_token: str = field(repr=False)

    async def query_bill(self, year: int, month: int) -> BillSummary:
        response = await self._get_bill(year, month)
        return BillSummary.model_validate(response.json())

    async def query_bill_details(self, year: int, month: int) -> BillDetails:
        response = await self._get_bill(year, month, suffix="/details")
        return BillDetails.model_validate(response.json())

    async def pay_bill(
        self, year: int, month: int, *, amount: Decimal, transaction_id: str
    ) -> PaymentResult:
        payload = PaymentRequest(amount=amount, transactionId=transaction_id)
        response = await self.http.post(
            f"{self._bill_path(year, month)}/payments",
            headers=self._headers(),
            json=payload.model_dump(mode="json", by_alias=True),
            follow_redirects=False,
        )
        response.raise_for_status()
        return PaymentResult.model_validate(response.json())

    def _bill_path(self, year: int, month: int) -> str:
        subscriber_no = quote(self.subscriber_no, safe="")
        return f"api/v1/subscribers/{subscriber_no}/bills/{year}/{month}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    async def _get_bill(self, year: int, month: int, *, suffix: str = "") -> httpx2.Response:
        response = await self.http.get(
            self._bill_path(year, month) + suffix,
            headers=self._headers(),
            follow_redirects=False,
        )
        response.raise_for_status()
        return response
