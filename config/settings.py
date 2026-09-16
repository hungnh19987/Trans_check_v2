"""
Cấu hình ứng dụng.

Toàn bộ giá trị nhạy cảm / phụ thuộc môi trường (BOT_TOKEN, NMS_HOST, ...)
được đọc từ biến môi trường (hoặc file .env nếu có), KHÔNG hard-code trong
source code.

Cách nạp:
- Nếu có cài `python-dotenv` và tồn tại file `.env` cạnh `run.py`, các biến
  trong đó sẽ được nạp vào environment trước khi đọc.
- Nếu thiếu biến bắt buộc, ứng dụng sẽ dừng ngay khi khởi động với thông báo
  rõ ràng, thay vì lỗi ngầm ở giữa luồng xử lý.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    # python-dotenv không bắt buộc; nếu không có, chỉ dùng env đã export sẵn.
    pass


class ConfigError(RuntimeError):
    """Lỗi cấu hình thiếu/sai khi khởi động."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Thiếu biến môi trường bắt buộc: {name}")
    return value


def _optional_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # --- Telegram ---
    bot_token: str
    allowed_group_id: int

    # --- Wyse -> NMS ---
    nms_host: str
    nms_user: str
    nms_ssh_port: int
    nms_ssh_key_path: str | None
    ssh_timeout: int  # giây, dùng cho cả bước Wyse->NMS và NMS->Device

    # --- NMS -> Device ---
    ssh_config_devices_path: str  # ví dụ: ~/.ssh/config.devices trên NMS
    # Lệnh shell tùy chọn chạy trên NMS trước khi gọi ssh xuống thiết bị, để
    # nạp lại ssh-agent đã unlock private key từ trước (ví dụ dùng
    # `keychain`). Không được để trống nếu key NMS->Device có passphrase,
    # nếu không mỗi lần bot chạy sẽ timeout (xem README).
    nms_remote_env_source: str | None

    # --- NMS -> Device (thiết bị xác thực bằng password, không có SSH key) ---
    # Thư mục trên NMS chứa file password riêng cho từng thiết bị (file tên
    # = hostname, nội dung = password thuần, do admin NMS tạo/quản lý thủ
    # công). Bot KHÔNG đọc nội dung file này, chỉ truyền đường dẫn cho
    # `sshpass -f` chạy trên NMS.
    device_password_secrets_dir: str | None
    sshpass_bin: str
    # Các giá trị của cột key_type trong Devices.csv được coi là "không có
    # SSH key, xác thực bằng password".
    password_key_types: frozenset[str]

    # --- Dữ liệu ---
    devices_csv_path: Path

    # --- Logging ---
    log_file_path: Path
    log_level: str


def load_settings() -> Settings:
    allowed_group_id_raw = _require_env("ALLOWED_GROUP_ID")
    try:
        allowed_group_id = int(allowed_group_id_raw)
    except ValueError as exc:
        raise ConfigError("ALLOWED_GROUP_ID phải là số nguyên (Telegram chat id)") from exc

    ssh_timeout_raw = _optional_env("SSH_TIMEOUT", "15")
    try:
        ssh_timeout = int(ssh_timeout_raw)
    except ValueError as exc:
        raise ConfigError("SSH_TIMEOUT phải là số nguyên (giây)") from exc

    nms_ssh_port_raw = _optional_env("NMS_SSH_PORT", "22")
    try:
        nms_ssh_port = int(nms_ssh_port_raw)
    except ValueError as exc:
        raise ConfigError("NMS_SSH_PORT phải là số nguyên") from exc

    return Settings(
        bot_token=_require_env("BOT_TOKEN"),
        allowed_group_id=allowed_group_id,
        nms_host=_require_env("NMS_HOST"),
        nms_user=_require_env("NMS_USER"),
        nms_ssh_port=nms_ssh_port,
        nms_ssh_key_path=os.environ.get("NMS_SSH_KEY_PATH") or None,
        ssh_timeout=ssh_timeout,
        ssh_config_devices_path=_optional_env(
            "SSH_CONFIG_DEVICES_PATH", "~/.ssh/config.devices"
        ),
        nms_remote_env_source=os.environ.get("NMS_REMOTE_ENV_SOURCE") or None,
        device_password_secrets_dir=os.environ.get("DEVICE_PASSWORD_SECRETS_DIR") or None,
        sshpass_bin=_optional_env("SSHPASS_BIN", "sshpass"),
        password_key_types=frozenset(
            v.strip().lower()
            for v in _optional_env("PASSWORD_KEY_TYPES", "non,none,password").split(",")
            if v.strip()
        ),
        devices_csv_path=Path(
            _optional_env("DEVICES_CSV_PATH", str(BASE_DIR / "data" / "Devices.csv"))
        ),
        log_file_path=Path(_optional_env("LOG_FILE_PATH", str(BASE_DIR / "logs" / "bot.log"))),
        log_level=_optional_env("LOG_LEVEL", "INFO"),
    )
