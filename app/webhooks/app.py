from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx
import stripe
from fastapi import FastAPI, HTTPException, Request
from stripe.error import SignatureVerificationError
from telegram.ext import Application


from app.config import Settings, resolve_plan
from app.db import Database
from app.payments.cryptobot import map_cryptobot_status, parse_cryptobot_webhook_body, verify_cryptobot_signature
from app.services.access import grant_access

logger = logging.getLogger(__name__)


def _paypal_api_base(env: str) -> str:
    return "https://api-m.paypal.com" if env == "live" else "https://api-m.sandbox.paypal.com"


async def _paypal_get_token(client_id: str, client_secret: str, api_base: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(base_url=api_base, timeout=30) as client:
        resp = await client.post(
            "/v1/oauth2/token",
            headers={"Authorization": f"Basic {basic}"},
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def _verify_paypal_webhook(
    *,
    settings: Settings,
    raw_body: bytes,
    headers: dict[str, str | None],
) -> dict[str, Any]:
    """Verify PayPal webhook using PayPal API (transmission headers + webhook id)."""
    if not settings.paypal_webhook_id:
        raise HTTPException(status_code=400, detail="PayPal webhook id not configured")
    required_keys = (
        "paypal-transmission-id",
        "paypal-transmission-time",
        "paypal-cert-url",
        "paypal-auth-algo",
        "paypal-transmission-sig",
    )
    hdr_out: dict[str, str] = {}
    for k in required_keys:
        v = headers.get(k)
        if not v:
            raise HTTPException(status_code=400, detail=f"Missing PayPal header: {k}")
        hdr_out[k] = v
    token = await _paypal_get_token(
        settings.paypal_client_id or "",
        settings.paypal_client_secret or "",
        _paypal_api_base(settings.paypal_env),
    )
    webhook_id = settings.paypal_webhook_id
    try:
        webhook_event = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid PayPal webhook JSON: {e}") from e
    payload: dict[str, Any] = {
        "transmission_id": hdr_out["paypal-transmission-id"],
        "transmission_time": hdr_out["paypal-transmission-time"],
        "cert_url": hdr_out["paypal-cert-url"],
        "auth_algo": hdr_out["paypal-auth-algo"],
        "transmission_sig": hdr_out["paypal-transmission-sig"],
        "webhook_id": webhook_id,
        "webhook_event": webhook_event,
    }
    async with httpx.AsyncClient(base_url=_paypal_api_base(settings.paypal_env), timeout=30) as client:
        resp = await client.post(
            "/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("verification_status") != "SUCCESS":
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook signature")
    return payload["webhook_event"]


async def _mark_paid_and_grant(
    *,
    db: Database,
    settings: Settings,
    bot: Any,
    payment_id: str,
    provider_ref: str | None,
) -> None:
    pay = db.get_payment(payment_id)
    if not pay:
        logger.warning("Webhook: unknown payment_id %s", payment_id)
        return
    if pay.status == "paid":
        return
    db.update_payment_status(payment_id, "paid", provider_ref)
    plan = resolve_plan(db, pay.plan_id)
    await grant_access(bot=bot, db=db, settings=settings, user_id=pay.user_id, plan=plan)


def create_webhook_app(application: Application) -> FastAPI:
    settings: Settings = application.bot_data["settings"]
    db: Database = application.bot_data["db"]

    app = FastAPI()

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> dict[str, str]:
        # Header: Stripe-Signature — secret: STRIPE_WEBHOOK_SECRET
        if not settings.stripe_webhook_secret:
            raise HTTPException(status_code=400, detail="Stripe webhook secret not configured")
        sig = request.headers.get("stripe-signature")
        if not sig:
            raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
        payload = await request.body()
        try:
            event = await asyncio.to_thread(
                stripe.Webhook.construct_event,
                payload,
                sig,
                settings.stripe_webhook_secret,
            )
        except SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid Stripe signature") from None

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            meta = session.get("metadata") or {}
            payment_id = meta.get("payment_id")
            if payment_id:
                await _mark_paid_and_grant(
                    db=db,
                    settings=settings,
                    bot=application.bot,
                    payment_id=payment_id,
                    provider_ref=session.get("id"),
                )
        return {"ok": "true"}

    @app.post("/webhooks/cryptobot")
    async def cryptobot_webhook(request: Request) -> dict[str, str]:
        # Header: crypto-pay-api-signature — secret: CRYPTOBOT_TOKEN (HMAC-SHA256 of raw body)
        if not settings.cryptobot_token:
            raise HTTPException(status_code=400, detail="CryptoBot token not configured")
        raw = await request.body()
        sig = request.headers.get("crypto-pay-api-signature")
        if not verify_cryptobot_signature(body=raw, signature_header=sig, token=settings.cryptobot_token):
            raise HTTPException(status_code=400, detail="Invalid CryptoBot signature")
        try:
            invoice_id, raw_status = parse_cryptobot_webhook_body(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid CryptoBot payload: {e}") from e
        vr = map_cryptobot_status(raw_status)
        pay = db.get_payment_by_provider_ref(provider="cryptobot", provider_ref=invoice_id)
        if not pay:
            return {"ok": "true"}
        if vr.status == "paid" and pay.status != "paid":
            await _mark_paid_and_grant(
                db=db,
                settings=settings,
                bot=application.bot,
                payment_id=pay.payment_id,
                provider_ref=invoice_id,
            )
        elif vr.status == "pending" and pay.status not in {"paid", "pending"}:
            db.update_payment_status(pay.payment_id, "pending", invoice_id)
        return {"ok": "true"}

    @app.post("/webhooks/paypal")
    async def paypal_webhook(request: Request) -> dict[str, str]:
        # Headers: PayPal-Transmission-Id, PayPal-Transmission-Time, PayPal-Cert-Url,
        # PayPal-Auth-Algo, PayPal-Transmission-Sig — verified via PayPal API using PAYPAL_WEBHOOK_ID
        raw = await request.body()
        hdrs = {k.lower(): v for k, v in request.headers.items()}
        transmission_headers = {
            "paypal-transmission-id": hdrs.get("paypal-transmission-id"),
            "paypal-transmission-time": hdrs.get("paypal-transmission-time"),
            "paypal-cert-url": hdrs.get("paypal-cert-url"),
            "paypal-auth-algo": hdrs.get("paypal-auth-algo"),
            "paypal-transmission-sig": hdrs.get("paypal-transmission-sig"),
        }
        try:
            event = await _verify_paypal_webhook(
                settings=settings,
                raw_body=raw,
                headers=transmission_headers,  # type: ignore[arg-type]
            )
        except httpx.HTTPStatusError:
            raise HTTPException(status_code=400, detail="PayPal verification request failed") from None

        event_type = event.get("event_type", "")
        resource = event.get("resource") or {}
        payment_id: str | None = None
        provider_ref: str | None = None

        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            provider_ref = resource.get("id")
            payment_id = resource.get("custom_id")
            if not payment_id:
                pu = (resource.get("supplementary_data") or {}).get("related_ids") or {}
                payment_id = pu.get("order_id")
        elif event_type in {"CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED"}:
            provider_ref = resource.get("id")
            for unit in resource.get("purchase_units") or []:
                payment_id = unit.get("reference_id") or payment_id

        if payment_id:
            pay = db.get_payment(payment_id)
            if pay and pay.provider == "paypal" and pay.status != "paid":
                await _mark_paid_and_grant(
                    db=db,
                    settings=settings,
                    bot=application.bot,
                    payment_id=payment_id,
                    provider_ref=provider_ref or pay.provider_ref,
                )
        return {"ok": "true"}

    return app
