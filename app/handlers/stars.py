from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.db import Database
from app.services.access import grant_access


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if not query:
        return
    payload = query.invoice_payload or ""
    user = query.from_user
    ok = False
    if user and "_" in payload:
        uid_s, _plan_id = payload.split("_", 1)
        if uid_s.isdigit() and int(uid_s) == user.id:
            ok = True
    await query.answer(ok=ok)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.successful_payment:
        return
    payload = message.successful_payment.invoice_payload or ""
    user = update.effective_user
    if not user:
        return
    if "_" not in payload:
        return
    uid_s, plan_id = payload.split("_", 1)
    if not uid_s.isdigit():
        return
    user_id = int(uid_s)
    if user_id != user.id:
        return
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    await grant_access(
        bot=context.bot,
        db=db,
        settings=settings,
        user_id=user_id,
        plan_id=plan_id,
    )
