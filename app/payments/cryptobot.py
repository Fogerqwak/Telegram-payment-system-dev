from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.payments.providers.base import PaymentProvider
from app.payments.types import CreatePaymentResult, VerifyResult


class CryptoBotProvider(PaymentProvider):
    name = "cryptobot"

    def __init__(self, *, api_token: str, api_base: str = "https://pay.crypt.bot") -> None:
        self._token = api_token
        self._api_base = api_base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Crypto-Pay-Api-Token": self._token,
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
        _ = currency  # USDT invoice; display currency may differ
        amount_str = f"{amount_cents / 100:.2f}"
        payload = f"{user_id}_{plan_id}"
        body = {
            "asset": "USDT",
            "amount": amount_str,
            "description": description,
            "payload": payload,
        }
        async with httpx.AsyncClient(base_url=f"{self._api_base}/api", timeout=30) as client:
            resp = await client.post("/createInvoice", headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"CryptoBot createInvoice failed: {data!r}")
        inv = data["result"]
        invoice_id = str(inv["invoice_id"])
        pay_url = str(inv["pay_url"])
        return CreatePaymentResult(provider="cryptobot", provider_ref=invoice_id, checkout_url=pay_url)

    async def verify_payment(self, *, provider_ref: str) -> VerifyResult:
        async with httpx.AsyncClient(base_url=f"{self._api_base}/api", timeout=30) as client:
            resp = await client.get(
                "/getInvoices",
                headers=self._headers(),
                params={"invoice_ids": provider_ref},
            )
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            return VerifyResult(status="failed", provider_ref=provider_ref)
        items = data.get("result", {}).get("items") or []
        if not items:
            return VerifyResult(status="failed", provider_ref=provider_ref)
        status = str(items[0].get("status") or "").lower()
        if status == "paid":
            return VerifyResult(status="paid", provider_ref=provider_ref)
        if status == "active":
            return VerifyResult(status="pending", provider_ref=provider_ref)
        return VerifyResult(status="pending", provider_ref=provider_ref)


def verify_cryptobot_signature(*, body: bytes, signature_header: str | None, token: str) -> bool:
    if not signature_header:
        return False
    expected = hmac.new(token.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def parse_cryptobot_webhook_body(body: bytes) -> tuple[str, str]:
    """Return (invoice_id, raw_status) from Crypto Pay webhook JSON."""
    data = json.loads(body.decode("utf-8"))
    inv: dict[str, Any] | None = None
    if data.get("update_type") == "invoice_paid":
        inv = data.get("payload")
    if isinstance(inv, dict) and "invoice_id" not in inv and isinstance(inv.get("invoice"), dict):
        inv = inv["invoice"]
    if not isinstance(inv, dict):
        inv = data.get("invoice") if isinstance(data.get("invoice"), dict) else None
    if not isinstance(inv, dict) or "invoice_id" not in inv:
        raise ValueError("CryptoBot webhook: missing invoice payload")
    invoice_id = str(inv["invoice_id"])
    status = str(inv.get("status", "paid")).lower()
    return invoice_id, status


def map_cryptobot_status(raw: str) -> VerifyResult:
    s = raw.lower()
    if s == "paid":
        return VerifyResult(status="paid")
    if s == "active":
        return VerifyResult(status="pending")
    return VerifyResult(status="pending")
