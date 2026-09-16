"""
Entry point của td-bot.

Chạy: python run.py
"""

from __future__ import annotations

import logging
import sys

from telegram.ext import Application

from bot.handlers.checktd import CheckTDHandler
from bot.router import register_routes
from commands.registry import CommandRegistry
from config.settings import ConfigError, load_settings
from device.repository import DeviceRepository, DeviceRepositoryError
from ssh.gateway import SSHGateway


def setup_logging(log_file_path, log_level: str) -> None:
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    # Giảm nhiễu log từ thư viện HTTP nội bộ của python-telegram-bot.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(settings.log_file_path, settings.log_level)
    logger = logging.getLogger("td_bot.run")

    try:
        device_repository = DeviceRepository(settings.devices_csv_path)
    except DeviceRepositoryError as exc:
        logger.error("Không thể khởi động: %s", exc)
        sys.exit(1)

    command_registry = CommandRegistry()

    ssh_gateway = SSHGateway(
        nms_host=settings.nms_host,
        nms_user=settings.nms_user,
        nms_port=settings.nms_ssh_port,
        nms_key_path=settings.nms_ssh_key_path,
        ssh_config_devices_path=settings.ssh_config_devices_path,
        timeout=settings.ssh_timeout,
        remote_env_source=settings.nms_remote_env_source,
        device_password_secrets_dir=settings.device_password_secrets_dir,
        sshpass_bin=settings.sshpass_bin,
        password_key_types=settings.password_key_types,
    )

    checktd_handler = CheckTDHandler(
        allowed_group_id=settings.allowed_group_id,
        device_repository=device_repository,
        command_registry=command_registry,
        ssh_gateway=ssh_gateway,
    )

    application = Application.builder().token(settings.bot_token).build()
    register_routes(application, checktd_handler)

    logger.info("td-bot đang khởi động (polling)...")
    # QUAN TRỌNG: phải khai báo cả "callback_query", nếu không Telegram sẽ
    # KHÔNG gửi sự kiện bấm nút (inline keyboard) về cho bot — nút bấm
    # trong /checktd sẽ không có phản hồi gì (chỉ tắt loading ở phía
    # client), dù server không báo lỗi.
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
