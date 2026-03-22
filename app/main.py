from __future__ import annotations

import asyncio
import logging

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from app.config import load_settings, seed_plans_from_settings
from app.db import Database
from app.handlers import (
    buy_start,
    cb_check_pay,
    cmd_buy,
    cmd_grant,
    cmd_revoke,
    cmd_setplan,
    cmd_start,
    cmd_status,
    payment_verifier_job,
    plan_selected,
    provider_selected,
    support_conversation_handler,
)
from app.handlers.stars import pre_checkout_handler, successful_payment_handler
from app.payments.router import build_providers
from app.services.subscription import expire_subscriptions
from app.webhooks.app import create_webhook_app


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def build_app() -> Application:
    settings = load_settings()
    db = Database(settings.db_path)
    seed_plans_from_settings(db, settings)

    application = Application.builder().token(settings.telegram_bot_token).build()
    providers = build_providers(settings, bot=application.bot)

    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.bot_data["providers"] = providers

    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.SUCCESSFUL_PAYMENT, successful_payment_handler)
    )

    application.add_handler(support_conversation_handler)
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("buy", cmd_buy))
    application.add_handler(CommandHandler("status", cmd_status))

    application.add_handler(CommandHandler("setplan", cmd_setplan))
    application.add_handler(CommandHandler("grant", cmd_grant))
    application.add_handler(CommandHandler("revoke", cmd_revoke))

    application.add_handler(CallbackQueryHandler(plan_selected, pattern=r"^plan:"))
    application.add_handler(CallbackQueryHandler(provider_selected, pattern=r"^pay:"))
    application.add_handler(CallbackQueryHandler(buy_start, pattern=r"^buy_back$"))
    application.add_handler(CallbackQueryHandler(cb_check_pay, pattern=r"^checkpay:"))

    application.job_queue.run_repeating(payment_verifier_job, interval=10, first=5, name="payment_verifier")
    return application


async def _run_bot(application: Application) -> None:
    await application.updater.start_polling(
        allowed_updates=["message", "callback_query", "pre_checkout_query"],
    )


async def main() -> None:
    application = build_app()
    settings = application.bot_data["settings"]
    db = application.bot_data["db"]

    await application.initialize()
    await application.start()

    scheduler = AsyncIOScheduler(timezone="UTC")

    async def expire_job() -> None:
        await expire_subscriptions(application.bot, settings, db)

    scheduler.add_job(expire_job, "interval", hours=1)
    scheduler.start()

    webhook_app = create_webhook_app(application)
    config = uvicorn.Config(
        webhook_app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(
            server.serve(),
            _run_bot(application),
        )
    finally:
        scheduler.shutdown(wait=False)
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
