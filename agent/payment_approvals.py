from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException

from agent.billing_agent import PaymentDraft


CONFIRMATION_TTL_SECONDS = 5 * 60


class PendingPayment(PaymentDraft):
    confirmation_id: UUID


@dataclass
class _Approval:
    subscriber_no: str
    payment: PendingPayment
    expires_at: float
    status: Literal["pending", "processing", "completed"] = "pending"


class PaymentApprovals:
    def __init__(self) -> None:
        self._approvals: dict[UUID, _Approval] = {}
        self._lock = Lock()

    def add(self, subscriber_no: str, draft: PaymentDraft) -> PendingPayment:
        payment = PendingPayment(**draft.model_dump(), confirmation_id=uuid4())
        now = monotonic()
        with self._lock:
            self._approvals = {
                key: approval for key, approval in self._approvals.items()
                if approval.expires_at > now
            }
            self._approvals[payment.confirmation_id] = _Approval(
                subscriber_no, payment, now + CONFIRMATION_TTL_SECONDS,
            )
        return payment

    @contextmanager
    def claim(self, confirmation_id: UUID, subscriber_no: str) -> Iterator[PendingPayment]:
        with self._lock:
            approval = self._approvals.get(confirmation_id)
            if (
                approval is None
                or approval.subscriber_no != subscriber_no
                or approval.expires_at <= monotonic()
            ):
                raise HTTPException(404, "Payment confirmation not found or expired")
            if approval.status != "pending":
                raise HTTPException(409, "Payment confirmation already used")
            approval.status = "processing"

        completed = False
        try:
            yield approval.payment
            completed = True
        finally:
            with self._lock:
                approval.status = "completed" if completed else "pending"
