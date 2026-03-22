from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import Settings, resolve_plan
from app.db import Database
from app.payments.router import Providers, describe, generate_payment_id, get_provider_by_name


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    plans = db.list_plans()
    if not plans:
        plan = resolve_plan(db, settings.default_plan_id)
        lines = [
            "This bot sells access to a private Telegram channel.\n\n",
            f"Default plan: **{plan.name}**\n",
            f"Price: **{plan.price_cents/100:.2f} {settings.display_currency}**\n",
            f"Duration: **{plan.duration_days} days**\n\n",
            "Use /buy to get a payment link.",
        ]
    else:
        lines = ["This bot sells access to a private Telegram channel.\n\n**Plans:**\n"]
        for p in plans:
            lines.append(
                f"- **{p.name}** — {p.price_cents/100:.2f} {settings.display_currency} "
                f"({p.duration_days} days)\n"
            )
        lines.append("\nUse /buy to choose a plan and pay.")
    await update.effective_message.reply_text("".join(lines), parse_mode=ParseMode.MARKDOWN)


def _plan_keyboard(db: Database) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in db.list_plans():
        rows.append([InlineKeyboardButton(p.name, callback_data=f"plan:{p.plan_id}")])
    return InlineKeyboardMarkup(rows)


def _provider_keyboard(providers: Providers, plan_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in providers.ordered:
        label = p.name.upper() if p.name != "mock" else "MOCK (test)"
        rows.append([InlineKeyboardButton(label, callback_data=f"pay:{plan_id}:{p.name}")])
    return InlineKeyboardMarkup(rows)


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    plans = db.list_plans()
    if not plans:
        await update.effective_message.reply_text("No plans configured. Ask an admin to add plans.")
        return
    await update.effective_message.reply_text("Choose a plan:", reply_markup=_plan_keyboard(db))


async def cb_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    _, plan_id = query.data.split(":", 1)
    providers: Providers = context.application.bot_data["providers"]
    await query.edit_message_text(
        text=f"Plan selected. Choose a payment provider for `{plan_id}`:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_provider_keyboard(providers, plan_id),
    )


async def cb_pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        await query.edit_message_text("Invalid callback. Use /buy again.")
        return
    _, plan_id, provider_name = parts

    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]

    user = query.from_user
    if not user:
        return

    try:
        provider = get_provider_by_name(providers, provider_name)
    except RuntimeError:
        await query.edit_message_text("That provider is not available.")
        return

    plan = resolve_plan(db, plan_id)
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

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 Pay now", url=result.checkout_url)],
            [InlineKeyboardButton("🔄 Check payment", callback_data=f"checkpay:{payment_id}")],
        ]
    )
    await query.edit_message_text(
        text=(
            f"Payment created.\n\n"
            f"- Provider: **{result.provider}**\n"
            f"- Payment ID: `{payment_id}`\n\n"
            f"Use the buttons below to pay or check status."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def cb_check_pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    _, payment_id = query.data.split(":", 1)

    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]

    payment = db.get_payment(payment_id)
    if not payment:
        await query.edit_message_text("Payment not found.")
        return

    if payment.provider_ref:
        provider = get_provider_by_name(providers, payment.provider)
        vr = await provider.verify_payment(provider_ref=payment.provider_ref)
        if vr.status == "paid" and payment.status != "paid":
            db.update_payment_status(payment_id, "paid", vr.provider_ref)
            plan = resolve_plan(db, payment.plan_id)
            from app.services.access import grant_access

            await grant_access(
                bot=context.bot,
                db=db,
                settings=settings,
                user_id=payment.user_id,
                plan=plan,
            )
            await query.edit_message_text("Payment confirmed — check your DM for the invite link.")
            return
        if vr.status in {"failed", "cancelled", "expired"} and payment.status not in {"paid"}:
            db.update_payment_status(payment_id, vr.status, vr.provider_ref)  # type: ignore[arg-type]

    payment = db.get_payment(payment_id) or payment
    await query.edit_message_text(
        f"Payment `{payment_id}` status: **{payment.status}**",
        parse_mode=ParseMode.MARKDOWN,
    )


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
        provider = get_provider_by_name(providers, payment.provider)
        vr = await provider.verify_payment(provider_ref=payment.provider_ref)
        if vr.status == "paid" and payment.status != "paid":
            db.update_payment_status(payment_id, "paid", vr.provider_ref)
            settings: Settings = context.application.bot_data["settings"]
            plan = resolve_plan(db, payment.plan_id)
            from app.services.access import grant_access

            await grant_access(
                bot=context.bot,
                db=db,
                settings=settings,
                user_id=payment.user_id,
                plan=plan,
            )
        elif vr.status in {"failed", "cancelled", "expired"} and payment.status not in {"paid"}:
            db.update_payment_status(payment_id, vr.status, vr.provider_ref)  # type: ignore[arg-type]
        payment = db.get_payment(payment_id) or payment

    await update.effective_message.reply_text(
        f"Payment `{payment.payment_id}` status: **{payment.status}**",
        parse_mode=ParseMode.MARKDOWN,
    )
