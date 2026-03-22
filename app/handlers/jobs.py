from __future__ import annotations

from telegram.ext import ContextTypes

from app.config import Settings, resolve_plan
from app.db import Database
from app.payments.router import Providers, get_provider_by_name
from app.services.access import grant_access


async def payment_verifier_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]

    pending = db.list_payments_by_status(["created", "pending"], limit=25)
    for p in pending:
        if not p.provider_ref:
            continue

        provider = get_provider_by_name(providers, p.provider)
        vr = await provider.verify_payment(provider_ref=p.provider_ref)

        if vr.status == "paid":
            if p.status != "paid":
                db.update_payment_status(p.payment_id, "paid", vr.provider_ref)
                plan = resolve_plan(db, p.plan_id)
                await grant_access(
                    bot=context.bot,
                    db=db,
                    settings=settings,
                    user_id=p.user_id,
                    plan=plan,
                )
        elif vr.status in {"failed", "cancelled", "expired"}:
            if p.status not in {"paid", vr.status}:
                db.update_payment_status(p.payment_id, vr.status, vr.provider_ref)  # type: ignore[arg-type]
