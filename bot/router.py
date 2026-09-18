"""Command routing."""

from __future__ import annotations

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot.handlers.checktd import CheckTDHandler


def register_routes(application: Application, checktd_handler: CheckTDHandler) -> None:
    application.add_handler(CommandHandler("checktd", checktd_handler.handle_search))
    application.add_handler(CallbackQueryHandler(checktd_handler.handle_selection, pattern=r"^checktd:\d+$"))
