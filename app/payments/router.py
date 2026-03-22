from __future__ import annotations

import secrets
from dataclasses import dataclass

from app.config import Plan, Settings
from app.payments.cryptobot import CryptoBotProvider
from app.payments.providers.base import PaymentProvider
from app.payments.providers.mock_provider import MockProvider
from app.payments.providers.paypal_provider import PayPalProvider
from app.payments.providers.stripe_provider import StripeProvider


@dataclass(frozen=True)
class Providers:
    ordered: list[PaymentProvider]


def build_providers(settings: Settings) -> Providers:
    providers: list[PaymentProvider] = []

    if settings.mock_payments:
        providers.append(MockProvider())

    if settings.stripe_enabled:
        if not (settings.stripe_secret_key and settings.stripe_success_url and settings.stripe_cancel_url):
            raise RuntimeError("Stripe enabled but STRIPE_SECRET_KEY / STRIPE_SUCCESS_URL / STRIPE_CANCEL_URL missing")
        providers.append(
            StripeProvider(
                secret_key=settings.stripe_secret_key,
                success_url=settings.stripe_success_url,
                cancel_url=settings.stripe_cancel_url,
            )
        )

    if settings.paypal_enabled:
        if not (
            settings.paypal_client_id
            and settings.paypal_client_secret
            and settings.paypal_return_url
            and settings.paypal_cancel_url
        ):
            raise RuntimeError(
                "PayPal enabled but PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET / PAYPAL_RETURN_URL / PAYPAL_CANCEL_URL missing"
            )
        providers.append(
            PayPalProvider(
                client_id=settings.paypal_client_id,
                client_secret=settings.paypal_client_secret,
                env=settings.paypal_env,
                return_url=settings.paypal_return_url,
                cancel_url=settings.paypal_cancel_url,
            )
        )

    if settings.cryptobot_enabled:
        if not settings.cryptobot_token:
            raise RuntimeError("CryptoBot enabled but CRYPTOBOT_TOKEN missing")
        providers.append(CryptoBotProvider(api_token=settings.cryptobot_token))

    if not providers:
        providers.append(MockProvider())

    return Providers(ordered=providers)


def generate_payment_id() -> str:
    return secrets.token_urlsafe(12)


def describe(plan: Plan, currency: str) -> str:
    price = f"{plan.price_cents / 100:.2f} {currency.upper()}"
    return f"{plan.name} ({price})"


def get_provider_by_name(providers: Providers, name: str):
    for p in providers.ordered:
        if p.name == name:
            return p
    raise RuntimeError(f"Provider not found: {name}")
