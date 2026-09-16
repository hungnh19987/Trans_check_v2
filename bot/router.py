"""
Command Router.

Ánh xạ mỗi Telegram command (/checktd, sau này /checkquang, /checkcpu, ...)
tới đúng một Handler class. Không đặt logic SSH/CSV trực tiếp ở đây — Router
chỉ đăng ký command với Handler.

Thêm command mới trong tương lai chỉ cần thêm một dòng `add_route(...)`,
không phải sửa SSH Gateway hay Telegram Layer.
"""

from __future__ import annotations

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot.handlers.checktd import CheckTDHandler


def register_routes(application: Application, checktd_handler: CheckTDHandler) -> None:
    application.add_handler(CommandHandler("checktd", checktd_handler.handle_search))
    application.add_handler(
        CallbackQueryHandler(checktd_handler.handle_selection, pattern=r"^checktd:\d+$")
    )

    # Chỗ mở rộng cho V2+ (không hiện thực trong phạm vi V1):
    # application.add_handler(CommandHandler("checkquang", check_optical_handler.handle))
    # application.add_handler(CommandHandler("checkcpu", check_cpu_handler.handle))
    # application.add_handler(CommandHandler("checkmemory", check_memory_handler.handle))
    # application.add_handler(CommandHandler("checkalarm", check_alarm_handler.handle))
    # application.add_handler(CommandHandler("checkversion", check_version_handler.handle))
