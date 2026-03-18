from __future__ import annotations

from datetime import datetime, timedelta, timezone

from telegram import Bot


async def create_invite_link(
    *,
    bot: Bot,
    chat_id: int,
    member_limit: int = 1,
    expire_seconds: int = 3600,
) -> str:
    now = datetime.now(timezone.utc)
    expire_date = now + timedelta(seconds=expire_seconds)
    link = await bot.create_chat_invite_link(
        chat_id=chat_id,
        member_limit=member_limit,
        expire_date=expire_date,
        creates_join_request=False,
    )
    return link.invite_link

