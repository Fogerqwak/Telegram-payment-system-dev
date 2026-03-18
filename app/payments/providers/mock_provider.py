from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.payments.providers.base import PaymentProvider
from app.payments.types import CreatePaymentResult, VerifyResult


@dataclass
class _MockState:
    created_at: datetime
    paid_after_seconds: int


class MockProvider(PaymentProvider):
    name = "mock"

    def __init__(self) -> None:
        self._state: dict[str, _MockState] = {}

    async def create_payment(
        self,
        *,
        payment_id: str,
        user_id: int,
        plan_id: str,
        amount_cents: int,
        currency: str,
        description: str,
    ) -> CreatePaymentResult:
        # deterministic "payment" progression for testing
        self._state[payment_id] = _MockState(
            created_at=datetime.now(timezone.utc),
            paid_after_seconds=10,
        )
        await asyncio.sleep(0)
        return CreatePaymentResult(
            provider="mock",
            provider_ref=payment_id,
            checkout_url=f"https://example.invalid/mock-checkout?payment_id={payment_id}",
        )

    async def verify_payment(self, *, provider_ref: str) -> VerifyResult:
        st = self._state.get(provider_ref)
        if not st:
            return VerifyResult(status="failed", provider_ref=provider_ref)
        now = datetime.now(timezone.utc)
        if now >= st.created_at + timedelta(seconds=st.paid_after_seconds):
            return VerifyResult(status="paid", provider_ref=provider_ref)
        return VerifyResult(status="pending", provider_ref=provider_ref)

