from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from app.db import Database, PlanRecord


@dataclass(frozen=True)
class Plan:
    plan_id: str
    name: str
    price_cents: int
    duration_days: int
    stars_price: int = 100


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(..., description="Telegram Bot API token")
    admin_user_ids: str = Field(default="", description="Comma-separated admin Telegram user IDs")
    support_user_ids: str = Field(
        default="",
        description="Comma-separated Telegram user IDs that receive /support messages; empty uses admin_user_ids",
    )
    protected_chat_id: int
    invite_link_expire_seconds: int = Field(default=3600)
    db_path: Path = Field(default=Path("./data/bot.sqlite3"))
    display_currency: str = Field(default="USD")
    default_plan_id: str = Field(default="monthly")
    available_plan_ids: str = Field(default="monthly", description="Comma-separated plan_ids seeded / shown in /buy")

    mock_payments: bool = Field(default=True)

    stars_enabled: bool = Field(default=False)

    stripe_enabled: bool = False
    stripe_secret_key: str | None = None
    stripe_success_url: str | None = None
    stripe_cancel_url: str | None = None
    stripe_webhook_secret: str | None = None

    paypal_enabled: bool = False
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_env: str = Field(default="sandbox")
    paypal_return_url: str | None = None
    paypal_cancel_url: str | None = None
    paypal_webhook_id: str | None = None

    cryptobot_enabled: bool = False
    cryptobot_token: str | None = None

    webhook_host: str = Field(default="0.0.0.0")
    webhook_port: int = Field(default=8000)

    @field_validator("db_path", mode="before")
    @classmethod
    def parse_db_path(cls, v: Any) -> Path:
        return Path(v) if not isinstance(v, Path) else v

    def admin_id_set(self) -> set[int]:
        return _parse_comma_separated_int_ids(self.admin_user_ids)

    def support_recipient_ids(self) -> set[int]:
        if self.support_user_ids.strip():
            return _parse_comma_separated_int_ids(self.support_user_ids)
        return self.admin_id_set()


def _parse_comma_separated_int_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return ids


def load_settings() -> Settings:
    return Settings()


def load_plan(plan_id: str) -> Plan:
    """Load plan fields from env (PLAN_<id>_*) for seeding and fallback."""
    load_dotenv()
    name = (os.getenv(f"PLAN_{plan_id}_NAME") or "").strip() or plan_id
    price_raw = os.getenv(f"PLAN_{plan_id}_PRICE_CENTS")
    duration_raw = os.getenv(f"PLAN_{plan_id}_DURATION_DAYS")
    stars_raw = os.getenv(f"PLAN_{plan_id}_STARS_PRICE")
    price_cents = int(price_raw) if price_raw not in (None, "") else 999
    duration_days = int(duration_raw) if duration_raw not in (None, "") else 30
    stars_price = int(stars_raw) if stars_raw not in (None, "") else 100
    return Plan(
        plan_id=plan_id,
        name=name,
        price_cents=price_cents,
        duration_days=duration_days,
        stars_price=stars_price,
    )


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "name": plan.name,
        "price_cents": plan.price_cents,
        "duration_days": plan.duration_days,
        "stars_price": plan.stars_price,
    }


def plan_record_to_plan(record: "PlanRecord") -> Plan:
    return Plan(
        plan_id=record.plan_id,
        name=record.name,
        price_cents=record.price_cents,
        duration_days=record.duration_days,
        stars_price=record.stars_price,
    )


def resolve_plan(db: "Database", plan_id: str) -> Plan:
    rec = db.get_plan_record(plan_id)
    if rec:
        return plan_record_to_plan(rec)
    return load_plan(plan_id)


def seed_plans_from_settings(db: "Database", settings: Settings) -> None:
    from app.db import PlanRecord

    if db.list_plans():
        return
    for pid in _split_plan_ids(settings.available_plan_ids):
        p = load_plan(pid)
        db.upsert_plan_record(
            PlanRecord(
                plan_id=p.plan_id,
                name=p.name,
                price_cents=p.price_cents,
                duration_days=p.duration_days,
                stars_price=p.stars_price,
            )
        )


def _split_plan_ids(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def list_plan_ids_from_settings(settings: Settings) -> list[str]:
    return _split_plan_ids(settings.available_plan_ids)
