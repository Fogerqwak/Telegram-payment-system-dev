from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderName = Literal["stripe", "paypal", "cryptobot", "mock"]


@dataclass(frozen=True)
class CreatePaymentResult:
    provider: ProviderName
    provider_ref: str | None
    checkout_url: str


@dataclass(frozen=True)
class VerifyResult:
    status: Literal["pending", "paid", "failed", "cancelled", "expired"]
    provider_ref: str | None = None

