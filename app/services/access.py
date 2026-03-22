from __future__ import annotations

from datetime import timedelta

from telegram import Bot

from app.config import Plan, Settings
from app.db import Database, utcnow


async def grant_access(
    *,
    bot: Bot,
    db: Database,
    settings: Settings,
    user_id: int,
    plan: Plan,
) -> None:
    """Create a short-lived invite link, notify the user, and extend subscription in the database."""
    expire_date = utcnow() + timedelta(minutes=10)
    link = await bot.create_chat_invite_link(
        chat_id=settings.protected_chat_id,
        member_limit=1,
        expire_date=expire_date,
        creates_join_request=False,
    )
    db.add_days(user_id, plan.plan_id, plan.duration_days)
    await bot.send_message(
        chat_id=user_id,
        text=(
            "Payment confirmed.\n\n"
            f"Here is your invite link (expires in 10 minutes):\n"
            f"{link.invite_link}"
        ),
    )
