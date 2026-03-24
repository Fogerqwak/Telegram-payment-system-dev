"""Reply keyboard under the message input (Telegram custom keyboard)."""

from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup

BTN_MENU_BUY = "🛒 Купить"
BTN_MENU_STATUS = "📋 Статус"
BTN_MENU_SUPPORT = "💬 Поддержка"


def main_menu_reply_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_MENU_BUY), KeyboardButton(BTN_MENU_STATUS)],
            [KeyboardButton(BTN_MENU_SUPPORT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Меню…",
    )
