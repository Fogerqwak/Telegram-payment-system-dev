from __future__ import annotations

from datetime import timedelta

from telegram import Bot

from app.config import Settings, resolve_plan
from app.db import Database, utcnow


async def grant_access(
    *,
    bot: Bot,
    db: Database,
    settings: Settings,
    user_id: int,
    plan_id: str,
) -> None:
    """Extend subscription, send a one-time invite link, and notify the user (Russian)."""
    plan = resolve_plan(db, plan_id)
    sub = db.add_days(user_id, plan.plan_id, plan.duration_days)
    expire_date = utcnow() + timedelta(minutes=15)
    link = await bot.create_chat_invite_link(
        chat_id=settings.protected_chat_id,
        member_limit=1,
        expire_date=expire_date,
        creates_join_request=False,
    )
    until = sub.active_until.strftime("%d.%m.%Y")
    await bot.send_message(
        chat_id=user_id,
        text=(
            "✅ Оплата получена!\n\n"
            f"Ваша подписка активна до: {until}\n\n"
            "🔗 Ссылка для входа (действует 15 минут):\n"
            f"{link.invite_link}\n\n"
            "⚠️ Ссылка одноразовая — не передавайте её другим."
        ),
    )
