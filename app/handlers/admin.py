from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import Settings, resolve_plan
from app.db import Database, PlanRecord


def _is_admin(settings: Settings, user_id: int | None) -> bool:
    return bool(user_id is not None and user_id in settings.admin_id_set())


async def cmd_setplan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    if not _is_admin(settings, update.effective_user.id if update.effective_user else None):
        await update.effective_message.reply_text("Not authorized.")
        return

    if len(context.args) < 4:
        await update.effective_message.reply_text("Usage: /setplan <plan_id> <name> <price_cents> <duration_days>")
        return

    plan_id = context.args[0].strip()
    name = context.args[1].strip()
    price_cents = int(context.args[2].strip())
    duration_days = int(context.args[3].strip())
    db.upsert_plan_record(
        PlanRecord(plan_id=plan_id, name=name, price_cents=price_cents, duration_days=duration_days)
    )
    await update.effective_message.reply_text(
        f"Plan `{plan_id}` saved to the database.",
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
    plan = resolve_plan(db, settings.default_plan_id)
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
