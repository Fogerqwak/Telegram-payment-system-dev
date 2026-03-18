from __future__ import annotations

import base64

import httpx

from app.payments.providers.base import PaymentProvider
from app.payments.types import CreatePaymentResult, VerifyResult


class PayPalProvider(PaymentProvider):
    name = "paypal"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        env: str,
        return_url: str,
        cancel_url: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._return_url = return_url
        self._cancel_url = cancel_url
        self._api_base = "https://api-m.paypal.com" if env == "live" else "https://api-m.sandbox.paypal.com"

    async def _get_access_token(self) -> str:
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        async with httpx.AsyncClient(base_url=self._api_base, timeout=30) as client:
            resp = await client.post(
                "/v1/oauth2/token",
                headers={"Authorization": f"Basic {basic}"},
                data={"grant_type": "client_credentials"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["access_token"]

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
        token = await self._get_access_token()
        amount = f"{amount_cents / 100:.2f}"
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": payment_id,
                    "description": description,
                    "amount": {"currency_code": currency.upper(), "value": amount},
                }
            ],
            "application_context": {
                "return_url": self._return_url,
                "cancel_url": self._cancel_url,
                "brand_name": "Telegram Access",
                "user_action": "PAY_NOW",
            },
        }

        async with httpx.AsyncClient(base_url=self._api_base, timeout=30) as client:
            resp = await client.post(
                "/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            order = resp.json()

        approve_url = None
        for link in order.get("links", []):
            if link.get("rel") == "approve":
                approve_url = link.get("href")
                break
        if not approve_url:
            raise RuntimeError("PayPal order created but approve URL missing")

        return CreatePaymentResult(provider="paypal", provider_ref=order["id"], checkout_url=approve_url)

    async def verify_payment(self, *, provider_ref: str) -> VerifyResult:
        token = await self._get_access_token()
        async with httpx.AsyncClient(base_url=self._api_base, timeout=30) as client:
            resp = await client.get(
                f"/v2/checkout/orders/{provider_ref}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            order = resp.json()

        status = (order.get("status") or "").upper()
        if status == "COMPLETED":
            return VerifyResult(status="paid", provider_ref=provider_ref)
        if status in {"CANCELLED", "VOIDED"}:
            return VerifyResult(status="cancelled", provider_ref=provider_ref)
        return VerifyResult(status="pending", provider_ref=provider_ref)

