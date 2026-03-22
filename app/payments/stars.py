from __future__ import annotations

from telegram import Bot, LabeledPrice

from app.payments.providers.base import PaymentProvider
from app.payments.types import CreatePaymentResult, VerifyResult


class StarsProvider(PaymentProvider):
    """Telegram Stars (XTR). Invoice is sent via Bot API; confirmation is push-based (handlers)."""

    name = "stars"

    def __init__(self, *, bot: Bot) -> None:
        self._bot = bot

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
        """Send Stars invoice. For this provider, ``amount_cents`` is the Stars amount (integer)."""
        _ = payment_id, currency
        stars_price = amount_cents
        payload = f"{user_id}_{plan_id}"
        if "\n" in description:
            title, body = description.split("\n", 1)
            title = title.strip()
            body = body.strip()
        else:
            title = description.strip()
            body = description.strip()
        label = title
        await self._bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=body,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label, stars_price)],
        )
        return CreatePaymentResult(provider="stars", provider_ref=payload, checkout_url="")

    async def verify_payment(self, *, provider_ref: str) -> VerifyResult:
        _ = provider_ref
        return VerifyResult(status="pending", provider_ref=provider_ref)

    async def handle_webhook(self, request_body: bytes) -> None:
        raise NotImplementedError("Stars payments are not confirmed via HTTP webhook")
