from __future__ import annotations

import logging

from telegram import Bot

from app.config import Settings
from app.db import Database

logger = logging.getLogger(__name__)


async def expire_subscriptions(bot: Bot, settings: Settings, db: Database) -> None:
    """Deactivate expired subscriptions, remove users from the protected chat, and notify them."""
    expired = db.list_expired_active_subscriptions()
    for sub in expired:
        uid = sub.user_id
        db.deactivate_subscription(uid)
        try:
            await bot.ban_chat_member(settings.protected_chat_id, uid)
            await bot.unban_chat_member(settings.protected_chat_id, uid)
        except Exception:
            logger.exception("ban/unban failed for user %s", uid)
        try:
            await bot.send_message(
                chat_id=uid,
                text="Your subscription has expired. Use /buy to renew.",
            )
        except Exception:
            logger.exception("notify expiry failed for user %s", uid)
