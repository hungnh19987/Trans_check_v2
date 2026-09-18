"""Entry point for td-bot with guarded startup and polling."""

from __future__ import annotations

import logging
import sys
import time

from telegram.ext import Application

from bot.errors import handle_error
from bot.handlers.checktd import CheckTDHandler
from bot.router import register_routes
from commands.registry import CommandRegistry
from config.settings import ConfigError, load_settings
from device.repository import DeviceRepository, DeviceRepositoryError
from ssh.gateway import SSHGateway


def setup_logging(log_file_path, log_level: str) -> None:
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not root_logger.handlers:
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_application(settings, device_repository: DeviceRepository) -> Application:
    gateway = SSHGateway(
        nms_host=settings.nms_host, nms_user=settings.nms_user,
        nms_port=settings.nms_ssh_port, nms_key_path=settings.nms_ssh_key_path,
        ssh_config_devices_path=settings.ssh_config_devices_path,
        timeout=settings.ssh_timeout, remote_env_source=settings.nms_remote_env_source,
        device_password_secrets_dir=settings.device_password_secrets_dir,
        sshpass_bin=settings.sshpass_bin, password_key_types=settings.password_key_types,
    )
    handler = CheckTDHandler(settings.allowed_group_id, device_repository, CommandRegistry(), gateway)
    application = Application.builder().token(settings.bot_token).build()
    register_routes(application, handler)
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    try:
        settings = load_settings()
        setup_logging(settings.log_file_path, settings.log_level)
        logger = logging.getLogger("td_bot.run")
        repository = DeviceRepository(settings.devices_csv_path)
    except (ConfigError, DeviceRepositoryError, OSError) as exc:
        print(f"[STARTUP ERROR] {exc}", file=sys.stderr)
        return

    retry_delay = 5
    while True:
        application = None
        try:
            application = build_application(settings, repository)
            logger.info("td-bot đang khởi động (polling)...")
            application.run_polling(allowed_updates=["message", "callback_query"])
            return
        except KeyboardInterrupt:
            logger.info("td-bot stopped by user")
            return
        except Exception:  # noqa: BLE001 - supervisor prevents transient crash
            logger.exception("Bot polling crashed; restarting in %ss", retry_delay)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
        finally:
            if application is not None:
                try:
                    application.stop_running()
                except Exception:  # noqa: BLE001
                    logger.exception("Error while stopping failed application")


if __name__ == "__main__":
    main()
