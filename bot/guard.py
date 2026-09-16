"""
Guard: chỉ cho phép bot xử lý command trong đúng một Telegram Group ID được
cấu hình (ALLOWED_GROUP_ID). Nếu message đến từ group khác, không xử lý và
không gửi thông báo lỗi.
"""

from __future__ import annotations

from telegram import Update


def is_allowed_chat(update: Update, allowed_group_id: int) -> bool:
    chat = update.effective_chat
    if chat is None:
        return False
    return chat.id == allowed_group_id
