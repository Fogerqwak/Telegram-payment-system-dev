from __future__ import annotations

from datetime import timedelta
from typing import cast

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import Plan, Settings, load_plan
from app.db import Database
from app.payments.router import Providers, describe, generate_payment_id
from app.payments.types import ProviderName
from app.services.access import create_invite_link


def _is_admin(settings: Settings, user_id: int | None) -> bool:
    return bool(user_id is not None and user_id in settings.admin_user_ids)


def _pick_provider(providers: Providers, requested: str | None) -> ProviderName:
    if requested:
        req = requested.strip().lower()
        for p in providers.ordered:
            if p.name == req:
                return cast(ProviderName, p.name)
        raise ValueError(f"Unknown/disabled provider: {requested}")

    # Prefer a real provider if enabled; otherwise mock.
    for p in providers.ordered:
        if p.name != "mock":
            return cast(ProviderName, p.name)
    return cast(ProviderName, providers.ordered[0].name)


def _get_provider_obj(providers: Providers, name: str):
    for p in providers.ordered:
        if p.name == name:
            return p
    raise RuntimeError(f"Provider not found: {name}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    plan = load_plan(settings.default_plan_id)
    txt = (
        "This bot sells access to a private Telegram channel.\n\n"
        f"Default plan: **{plan.name}**\n"
        f"Price: **{plan.price_cents/100:.2f} {settings.display_currency}**\n"
        f"Duration: **{plan.duration_days} days**\n\n"
        "Use /buy to get a payment link."
    )
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]

    user = update.effective_user
    if not user:
        return

    requested_provider = context.args[0] if context.args else None
    try:
        provider_name = _pick_provider(providers, requested_provider)
    except ValueError as e:
        await update.effective_message.reply_text(str(e))
        return

    provider = _get_provider_obj(providers, provider_name)

    plan: Plan = load_plan(settings.default_plan_id)
    payment_id = generate_payment_id()
    currency = settings.display_currency.upper()
    result = await provider.create_payment(
        payment_id=payment_id,
        user_id=user.id,
        plan_id=plan.plan_id,
        amount_cents=plan.price_cents,
        currency=currency,
        description=describe(plan, currency),
    )

    db.create_payment(
        payment_id=payment_id,
        user_id=user.id,
        provider=result.provider,
        plan_id=plan.plan_id,
        amount_cents=plan.price_cents,
        currency=currency,
        status="created",
        checkout_url=result.checkout_url,
        provider_ref=result.provider_ref,
    )

    txt = (
        f"Payment created.\n\n"
        f"- Provider: **{result.provider}**\n"
        f"- Payment ID: `{payment_id}`\n\n"
        f"Pay here: {result.checkout_url}\n\n"
        f"Check status: `/status {payment_id}`"
    )
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]

    if not context.args:
        await update.effective_message.reply_text("Usage: /status <payment_id>")
        return

    payment_id = context.args[0].strip()
    payment = db.get_payment(payment_id)
    if not payment:
        await update.effective_message.reply_text("Payment not found.")
        return

    if payment.provider_ref:
        provider = _get_provider_obj(providers, payment.provider)
        vr = await provider.verify_payment(provider_ref=payment.provider_ref)
        if vr.status == "paid" and payment.status != "paid":
            db.update_payment_status(payment_id, "paid", vr.provider_ref)
        elif vr.status in {"failed", "cancelled", "expired"} and payment.status not in {"paid"}:
            db.update_payment_status(payment_id, vr.status, vr.provider_ref)  # type: ignore[arg-type]
        payment = db.get_payment(payment_id) or payment

    await update.effective_message.reply_text(
        f"Payment `{payment.payment_id}` status: **{payment.status}**",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_setplan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_admin(settings, update.effective_user.id if update.effective_user else None):
        await update.effective_message.reply_text("Not authorized.")
        return

    if len(context.args) < 4:
        await update.effective_message.reply_text("Usage: /setplan <plan_id> <name> <price_cents> <duration_days>")
        return

    # For base: this just tells you which env vars to set (plans are env-defined).
    plan_id = context.args[0].strip()
    name = context.args[1].strip()
    price_cents = int(context.args[2].strip())
    duration_days = int(context.args[3].strip())
    await update.effective_message.reply_text(
        "Plans are configured via env for now.\n\n"
        f"Add these to `.env`:\n"
        f"`PLAN_{plan_id}_NAME={name}`\n"
        f"`PLAN_{plan_id}_PRICE_CENTS={price_cents}`\n"
        f"`PLAN_{plan_id}_DURATION_DAYS={duration_days}`\n"
        f"Then set `DEFAULT_PLAN_ID={plan_id}` and restart.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    if not _is_admin(settings, update.effective_user.id if update.effective_user else None):
        await update.effective_message.reply_text("Not authorized.")
        return

    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /grant <user_id> <days>")
        return

    user_id = int(context.args[0])
    days = int(context.args[1])
    plan = load_plan(settings.default_plan_id)
    sub = db.add_days(user_id, plan.plan_id, days)
    await update.effective_message.reply_text(f"Granted until {sub.active_until.isoformat()}")


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    if not _is_admin(settings, update.effective_user.id if update.effective_user else None):
        await update.effective_message.reply_text("Not authorized.")
        return

    if len(context.args) < 1:
        await update.effective_message.reply_text("Usage: /revoke <user_id>")
        return

    user_id = int(context.args[0])
    db.revoke_subscription(user_id)
    await update.effective_message.reply_text("Revoked.")


async def payment_verifier_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]

    pending = db.list_payments_by_status(["created", "pending"], limit=25)
    for p in pending:
        if not p.provider_ref:
            continue

        provider = _get_provider_obj(providers, p.provider)
        vr = await provider.verify_payment(provider_ref=p.provider_ref)

        if vr.status == "paid":
            if p.status != "paid":
                db.update_payment_status(p.payment_id, "paid", vr.provider_ref)
                plan = load_plan(p.plan_id)
                db.add_days(p.user_id, p.plan_id, plan.duration_days)
                invite = await create_invite_link(
                    bot=context.bot,
                    chat_id=settings.protected_chat_id,
                    expire_seconds=settings.invite_link_expire_seconds,
                    member_limit=1,
                )
                await context.bot.send_message(
                    chat_id=p.user_id,
                    text=(
                        "Payment confirmed.\n\n"
                        f"Here is your invite link (expires in {settings.invite_link_expire_seconds//60} min):\n"
                        f"{invite}"
                    ),
                )
        elif vr.status in {"failed", "cancelled", "expired"}:
            if p.status not in {"paid", vr.status}:
                db.update_payment_status(p.payment_id, vr.status, vr.provider_ref)  # type: ignore[arg-type]

