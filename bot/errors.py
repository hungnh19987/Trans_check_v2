"""Application-wide Telegram error handling."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger("td_bot.errors")


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every uncaught update error without allowing it to kill polling."""
    logger.error("Unhandled Telegram update error", exc_info=context.error)
    if not isinstance(update, Update):
        return
    message = update.effective_message
    if message is None:
        return
    try:
        await message.reply_text(
            "❌ Bot gặp lỗi tạm thời khi xử lý yêu cầu. Vui lòng thử lại sau.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:  # noqa: BLE001 - Telegram failure must not cascade
        logger.exception("Could not send the generic error response")
