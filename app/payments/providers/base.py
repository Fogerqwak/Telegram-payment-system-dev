from __future__ import annotations

from abc import ABC, abstractmethod

from app.payments.types import CreatePaymentResult, VerifyResult


class PaymentProvider(ABC):
    name: str

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def verify_payment(self, *, provider_ref: str) -> VerifyResult:
        raise NotImplementedError

