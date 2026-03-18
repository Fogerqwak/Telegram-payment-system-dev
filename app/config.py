from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import os


def _get_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return int(v)


def _get_str(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v != "" else default


def _get_required(name: str) -> str:
    v = _get_str(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _get_admin_ids() -> set[int]:
    raw = _get_str("ADMIN_USER_IDS", "") or ""
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return ids


@dataclass(frozen=True)
class Plan:
    plan_id: str
    name: str
    price_cents: int
    duration_days: int


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_user_ids: set[int]
    protected_chat_id: int
    invite_link_expire_seconds: int
    db_path: Path
    display_currency: str
    default_plan_id: str

    mock_payments: bool

    stripe_enabled: bool
    stripe_secret_key: str | None
    stripe_success_url: str | None
    stripe_cancel_url: str | None

    paypal_enabled: bool
    paypal_client_id: str | None
    paypal_client_secret: str | None
    paypal_env: str
    paypal_return_url: str | None
    paypal_cancel_url: str | None

    coinbase_enabled: bool
    coinbase_api_key: str | None
    coinbase_webhook_shared_secret: str | None


def load_settings() -> Settings:
    load_dotenv()

    token = _get_required("TELEGRAM_BOT_TOKEN")
    protected_chat_id = int(_get_required("PROTECTED_CHAT_ID"))
    db_path = Path(_get_str("DB_PATH", "./data/bot.sqlite3") or "./data/bot.sqlite3")
    display_currency = _get_str("DISPLAY_CURRENCY", "USD") or "USD"
    default_plan_id = _get_str("DEFAULT_PLAN_ID", "monthly") or "monthly"

    return Settings(
        telegram_bot_token=token,
        admin_user_ids=_get_admin_ids(),
        protected_chat_id=protected_chat_id,
        invite_link_expire_seconds=_get_int("INVITE_LINK_EXPIRE_SECONDS", 3600),
        db_path=db_path,
        display_currency=display_currency,
        default_plan_id=default_plan_id,
        mock_payments=_get_bool("MOCK_PAYMENTS", True),
        stripe_enabled=_get_bool("STRIPE_ENABLED", False),
        stripe_secret_key=_get_str("STRIPE_SECRET_KEY"),
        stripe_success_url=_get_str("STRIPE_SUCCESS_URL"),
        stripe_cancel_url=_get_str("STRIPE_CANCEL_URL"),
        paypal_enabled=_get_bool("PAYPAL_ENABLED", False),
        paypal_client_id=_get_str("PAYPAL_CLIENT_ID"),
        paypal_client_secret=_get_str("PAYPAL_CLIENT_SECRET"),
        paypal_env=_get_str("PAYPAL_ENV", "sandbox") or "sandbox",
        paypal_return_url=_get_str("PAYPAL_RETURN_URL"),
        paypal_cancel_url=_get_str("PAYPAL_CANCEL_URL"),
        coinbase_enabled=_get_bool("COINBASE_ENABLED", False),
        coinbase_api_key=_get_str("COINBASE_API_KEY"),
        coinbase_webhook_shared_secret=_get_str("COINBASE_WEBHOOK_SHARED_SECRET"),
    )


def load_plan(plan_id: str) -> Plan:
    name = _get_str(f"PLAN_{plan_id}_NAME", plan_id) or plan_id
    price_cents = _get_int(f"PLAN_{plan_id}_PRICE_CENTS", 999)
    duration_days = _get_int(f"PLAN_{plan_id}_DURATION_DAYS", 30)
    return Plan(plan_id=plan_id, name=name, price_cents=price_cents, duration_days=duration_days)


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "name": plan.name,
        "price_cents": plan.price_cents,
        "duration_days": plan.duration_days,
    }

