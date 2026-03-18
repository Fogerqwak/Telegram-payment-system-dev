from __future__ import annotations

import httpx

from app.payments.providers.base import PaymentProvider
from app.payments.types import CreatePaymentResult, VerifyResult


class CoinbaseCommerceProvider(PaymentProvider):
    name = "coinbase"

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key
        self._api_base = "https://api.commerce.coinbase.com"

    def _headers(self) -> dict[str, str]:
        return {
            "X-CC-Api-Key": self._api_key,
            "X-CC-Version": "2018-03-22",
            "Content-Type": "application/json",
        }

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
        # Coinbase Commerce supports multiple crypto assets including stablecoins depending on account.
        amount = f"{amount_cents / 100:.2f}"
        payload = {
            "name": description,
            "description": f"Telegram access: {plan_id}",
            "pricing_type": "fixed_price",
            "local_price": {"amount": amount, "currency": currency.upper()},
            "metadata": {"payment_id": payment_id, "user_id": str(user_id), "plan_id": plan_id},
        }
        async with httpx.AsyncClient(base_url=self._api_base, timeout=30) as client:
            resp = await client.post("/charges", headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()["data"]
        return CreatePaymentResult(provider="coinbase", provider_ref=data["id"], checkout_url=data["hosted_url"])

    async def verify_payment(self, *, provider_ref: str) -> VerifyResult:
        async with httpx.AsyncClient(base_url=self._api_base, timeout=30) as client:
            resp = await client.get(f"/charges/{provider_ref}", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()["data"]

        # status values: NEW, PENDING, COMPLETED, EXPIRED, UNRESOLVED, CANCELED (varies)
        status = (data.get("timeline", [])[-1].get("status") if data.get("timeline") else data.get("status")) or ""
        status = str(status).upper()
        if status in {"COMPLETED", "CONFIRMED", "RESOLVED"}:
            return VerifyResult(status="paid", provider_ref=provider_ref)
        if status in {"EXPIRED"}:
            return VerifyResult(status="expired", provider_ref=provider_ref)
        if status in {"CANCELED", "CANCELLED"}:
            return VerifyResult(status="cancelled", provider_ref=provider_ref)
        if status in {"UNRESOLVED"}:
            return VerifyResult(status="failed", provider_ref=provider_ref)
        return VerifyResult(status="pending", provider_ref=provider_ref)

