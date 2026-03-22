from __future__ import annotations

import asyncio
import logging

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from app.config import load_settings, seed_plans_from_settings
from app.db import Database
from app.handlers import (
    cb_check_pay,
    cb_pay,
    cb_plan,
    cmd_buy,
    cmd_grant,
    cmd_revoke,
    cmd_setplan,
    cmd_start,
    cmd_status,
    payment_verifier_job,
)
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
    providers = build_providers(settings)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.bot_data["providers"] = providers

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("buy", cmd_buy))
    application.add_handler(CommandHandler("status", cmd_status))

    application.add_handler(CommandHandler("setplan", cmd_setplan))
    application.add_handler(CommandHandler("grant", cmd_grant))
    application.add_handler(CommandHandler("revoke", cmd_revoke))

    application.add_handler(CallbackQueryHandler(cb_plan, pattern=r"^plan:"))
    application.add_handler(CallbackQueryHandler(cb_pay, pattern=r"^pay:"))
    application.add_handler(CallbackQueryHandler(cb_check_pay, pattern=r"^checkpay:"))

    application.job_queue.run_repeating(payment_verifier_job, interval=10, first=5, name="payment_verifier")
    return application


async def _run_bot(application: Application) -> None:
    await application.updater.start_polling(allowed_updates=["message", "callback_query"])
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await application.updater.stop()


async def main() -> None:
    application = build_app()
    settings = application.bot_data["settings"]
    db = application.bot_data["db"]

    await application.initialize()
    await application.start()

    scheduler = AsyncIOScheduler()

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
