from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import Settings, resolve_plan
from app.db import Database, utcnow
from app.payments.router import Providers, describe, generate_payment_id, get_provider_by_name
from app.services.access import grant_access


logger = logging.getLogger(__name__)


def _provider_key_to_name(key: str) -> str:
    if key == "crypto":
        return "cryptobot"
    return key


def _has_any_payment_provider(settings: Settings) -> bool:
    return bool(
        settings.stars_enabled
        or settings.cryptobot_enabled
        or settings.stripe_enabled
        or settings.paypal_enabled
        or settings.mock_payments
    )


def _plan_keyboard(db: Database) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in db.list_plans():
        price_usd = p.price_cents / 100
        label = f"{p.name} — {p.stars_price}⭐ / ${price_usd:.2f}"
        rows.append([InlineKeyboardButton(label, callback_data=f"plan:{p.plan_id}")])
    return InlineKeyboardMarkup(rows)


def _provider_keyboard(settings: Settings, plan_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.stars_enabled:
        rows.append([InlineKeyboardButton("⭐ Telegram Stars", callback_data=f"pay:{plan_id}:stars")])
    if settings.cryptobot_enabled:
        rows.append([InlineKeyboardButton("💎 USDT (CryptoBot)", callback_data=f"pay:{plan_id}:crypto")])
    if settings.stripe_enabled:
        rows.append([InlineKeyboardButton("💳 Card (Stripe)", callback_data=f"pay:{plan_id}:stripe")])
    if settings.paypal_enabled:
        rows.append([InlineKeyboardButton("PayPal", callback_data=f"pay:{plan_id}:paypal")])
    if settings.mock_payments:
        rows.append([InlineKeyboardButton("MOCK (тест)", callback_data=f"pay:{plan_id}:mock")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="buy_back")])
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Добро пожаловать! Нажмите /buy чтобы получить доступ."
    )


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    plans = db.list_plans()
    if not plans:
        await update.effective_message.reply_text(
            "Планы не настроены. Обратитесь к администратору."
        )
        return
    await update.effective_message.reply_text(
        "Выберите тариф:",
        reply_markup=_plan_keyboard(db),
    )


async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    _, plan_id = query.data.split(":", 1)
    settings: Settings = context.application.bot_data["settings"]
    if not _has_any_payment_provider(settings):
        await query.edit_message_text("Нет доступных способов оплаты.")
        return
    await query.edit_message_text(
        "Выберите способ оплаты:",
        reply_markup=_provider_keyboard(settings, plan_id),
    )


async def buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    db: Database = context.application.bot_data["db"]
    await query.edit_message_text(
        "Выберите тариф:",
        reply_markup=_plan_keyboard(db),
    )


async def provider_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        await query.edit_message_text("Неверные данные. Начните снова: /buy")
        return
    _, plan_id, provider_key = parts
    provider_name = _provider_key_to_name(provider_key)

    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]

    user = query.from_user
    if not user:
        return

    try:
        provider = get_provider_by_name(providers, provider_name)
    except RuntimeError:
        await query.edit_message_text("Этот способ оплаты недоступен.")
        return

    plan = resolve_plan(db, plan_id)
    currency = settings.display_currency.upper()

    try:
        if provider_name == "stars":
            stars_desc = f"{plan.name}\nПодписка на {plan.duration_days} дн."
            await provider.create_payment(
                payment_id="",
                user_id=user.id,
                plan_id=plan.plan_id,
                amount_cents=plan.stars_price,
                currency="XTR",
                description=stars_desc,
            )
            await query.edit_message_text(
                "⏳ Ожидаем оплату...",
                reply_markup=None,
            )
            return

        payment_id = generate_payment_id()
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
            status="pending",
            checkout_url=result.checkout_url,
            provider_ref=result.provider_ref,
        )

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("💳 Оплатить", url=result.checkout_url)],
                [InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"checkpay:{payment_id}")],
            ]
        )
        await query.edit_message_text(
            "⏳ Ожидаем оплату...\n\n"
            f"Способ: **{result.provider}**\n"
            f"ID платежа: `{payment_id}`\n\n"
            "Используйте кнопки ниже.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
    except Exception:
        logger.exception("provider_selected failed")
        await query.edit_message_text(
            "Что-то пошло не так. Попробуйте снова или напишите администратору."
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
        await query.edit_message_text("Платёж не найден.")
        return

    if payment.provider == "stars":
        await query.edit_message_text("Оплата Stars подтверждается автоматически в чате.")
        return

    if payment.provider_ref:
        provider = get_provider_by_name(providers, payment.provider)
        vr = await provider.verify_payment(provider_ref=payment.provider_ref)
        if vr.status == "paid" and payment.status != "paid":
            db.update_payment_status(payment_id, "paid", vr.provider_ref)
            await grant_access(
                bot=context.bot,
                db=db,
                settings=settings,
                user_id=payment.user_id,
                plan_id=payment.plan_id,
            )
            await query.edit_message_text("Оплату подтверждено — проверьте личные сообщения со ссылкой.")
            return
        if vr.status in {"failed", "cancelled", "expired"} and payment.status not in {"paid"}:
            db.update_payment_status(payment_id, vr.status, vr.provider_ref)  # type: ignore[arg-type]

    payment = db.get_payment(payment_id) or payment
    await query.edit_message_text(
        f"Статус платежа `{payment_id}`: **{payment.status}**",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    providers: Providers = context.application.bot_data["providers"]
    settings: Settings = context.application.bot_data["settings"]

    if not context.args:
        user = update.effective_user
        if not user:
            return
        sub = db.get_subscription(user.id)
        now = utcnow()
        if sub and sub.active and sub.active_until > now:
            await update.effective_message.reply_text(
                f"✅ Подписка активна до {sub.active_until.strftime('%d.%m.%Y')}"
            )
        else:
            await update.effective_message.reply_text("❌ Подписка не найдена")
        return

    payment_id = context.args[0].strip()
    payment = db.get_payment(payment_id)
    if not payment:
        await update.effective_message.reply_text("Платёж не найден.")
        return

    if payment.provider_ref:
        provider = get_provider_by_name(providers, payment.provider)
        vr = await provider.verify_payment(provider_ref=payment.provider_ref)
        if vr.status == "paid" and payment.status != "paid":
            db.update_payment_status(payment_id, "paid", vr.provider_ref)
            await grant_access(
                bot=context.bot,
                db=db,
                settings=settings,
                user_id=payment.user_id,
                plan_id=plan.plan_id,
            )
        elif vr.status in {"failed", "cancelled", "expired"} and payment.status not in {"paid"}:
            db.update_payment_status(payment_id, vr.status, vr.provider_ref)  # type: ignore[arg-type]
        payment = db.get_payment(payment_id) or payment

    await update.effective_message.reply_text(
        f"Статус платежа `{payment.payment_id}`: **{payment.status}**",
        parse_mode=ParseMode.MARKDOWN,
    )


WAITING_SUPPORT = 1

_SUPPORT_MESSAGE_FILTER = (
    filters.ChatType.PRIVATE & (filters.TEXT | filters.ATTACHMENT) & ~filters.COMMAND
)


async def _forward_support_message(
    context: ContextTypes.DEFAULT_TYPE,
    settings: Settings,
    from_chat_id: int,
    message_id: int,
) -> tuple[int, int]:
    recipients = settings.support_recipient_ids()
    ok = 0
    fail = 0
    for uid in recipients:
        try:
            await context.bot.forward_message(
                chat_id=uid,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            ok += 1
        except TelegramError:
            logger.exception("Forwarding support message to %s failed", uid)
            fail += 1
    return ok, fail


async def support_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return ConversationHandler.END
    settings: Settings = context.application.bot_data["settings"]
    if not settings.support_recipient_ids():
        await message.reply_text("Поддержка пока не настроена. Попробуйте позже.")
        return ConversationHandler.END
    await message.reply_text(
        "Отправьте сообщение в поддержку (текст или вложения). "
        "Можно отправить несколько сообщений. "
        "Когда закончите, отправьте /cancel.\n\n"
        "Для других команд бота (например /buy) сначала отправьте /cancel."
    )
    return WAITING_SUPPORT


async def support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if not message:
        return WAITING_SUPPORT
    settings: Settings = context.application.bot_data["settings"]
    if not settings.support_recipient_ids():
        await message.reply_text("Поддержка не настроена.")
        return ConversationHandler.END
    chat = update.effective_chat
    if not chat:
        return WAITING_SUPPORT
    ok, _fail = await _forward_support_message(
        context, settings, from_chat_id=chat.id, message_id=message.message_id
    )
    if ok == 0:
        await message.reply_text(
            "Не удалось доставить сообщение. Попробуйте позже или свяжитесь с нами иначе."
        )
    else:
        await message.reply_text("Сообщение отправлено в поддержку.")
    return WAITING_SUPPORT


async def support_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if message:
        await message.reply_text("Чат с поддержкой закрыт.")
    return ConversationHandler.END


support_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("support", support_entry, filters=filters.ChatType.PRIVATE),
    ],
    states={
        WAITING_SUPPORT: [
            MessageHandler(_SUPPORT_MESSAGE_FILTER, support_receive),
        ],
    },
    fallbacks=[CommandHandler("cancel", support_cancel)],
    name="support",
)
