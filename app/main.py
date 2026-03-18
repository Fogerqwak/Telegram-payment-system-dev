from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler

from app.config import load_settings
from app.db import Database
from app.handlers import (
    cmd_buy,
    cmd_grant,
    cmd_revoke,
    cmd_setplan,
    cmd_start,
    cmd_status,
    payment_verifier_job,
)
from app.payments.router import build_providers


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def build_app() -> Application:
    settings = load_settings()
    db = Database(settings.db_path)
    providers = build_providers(settings)

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db
    app.bot_data["providers"] = providers

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CommandHandler("setplan", cmd_setplan))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))

    # Poll pending payments periodically (webhooks can replace this later).
    app.job_queue.run_repeating(payment_verifier_job, interval=10, first=5, name="payment_verifier")
    return app


def main() -> None:
    app = build_app()
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()

