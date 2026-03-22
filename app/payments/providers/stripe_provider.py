from __future__ import annotations

import asyncio

import stripe

from app.payments.providers.base import PaymentProvider
from app.payments.types import CreatePaymentResult, VerifyResult


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self, *, secret_key: str, success_url: str, cancel_url: str) -> None:
        stripe.api_key = secret_key
        self._success_url = success_url
        self._cancel_url = cancel_url

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
        def _create() -> CreatePaymentResult:
            session = stripe.checkout.Session.create(
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "product_data": {"name": description},
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                metadata={
                    "payment_id": payment_id,
                    "user_id": str(user_id),
                    "plan_id": plan_id,
                },
                success_url=self._success_url,
                cancel_url=self._cancel_url,
            )
            url = session.url or ""
            return CreatePaymentResult(provider="stripe", provider_ref=session.id, checkout_url=url)

        return await asyncio.to_thread(_create)

    async def verify_payment(self, *, provider_ref: str) -> VerifyResult:
        def _retrieve() -> VerifyResult:
            session = stripe.checkout.Session.retrieve(provider_ref)
            if session.payment_status == "paid":
                return VerifyResult(status="paid", provider_ref=session.id)
            if session.status == "expired":
                return VerifyResult(status="expired", provider_ref=session.id)
            return VerifyResult(status="pending", provider_ref=session.id)

        return await asyncio.to_thread(_retrieve)
