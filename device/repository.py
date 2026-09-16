"""
Device Repository.

Module DUY NHẤT chịu trách nhiệm đọc `Devices.csv`. Các Handler không được
tự đọc CSV mà phải gọi qua repository này.
"""

from __future__ import annotations

import csv
import logging
import threading
from pathlib import Path

from device.models import Device

logger = logging.getLogger("td_bot.device_repository")

REQUIRED_COLUMNS = [
    "hostname",
    "management_ip",
    "vendor",
    "model",
    "role",
    "province",
    "ssh_user",
    "description",
    "key_type",
]

# Cột tùy chọn: không bắt buộc phải có trong Devices.csv (để tương thích
# ngược với file cũ chưa có cột này). Nếu thiếu, coi như alias rỗng cho mọi
# thiết bị.
OPTIONAL_COLUMNS = ["alias"]


class DeviceRepositoryError(RuntimeError):
    """Lỗi khi đọc/parse Devices.csv."""


class DeviceRepository:
    """
    Đọc Devices.csv và cung cấp `get_device(hostname)`.

    Nạp toàn bộ danh sách vào bộ nhớ và cache lại; có khóa (lock) để an toàn
    khi nhiều lệnh Telegram được xử lý đồng thời.
    """

    def __init__(self, csv_path: Path) -> None:
        self._csv_path = csv_path
        self._lock = threading.Lock()
        self._devices_by_hostname: dict[str, Device] = {}
        self._load()

    def _load(self) -> None:
        if not self._csv_path.exists():
            raise DeviceRepositoryError(f"Không tìm thấy file Devices.csv: {self._csv_path}")

        with self._csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                raise DeviceRepositoryError("Devices.csv rỗng hoặc không có header.")

            missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
            if missing:
                raise DeviceRepositoryError(
                    f"Devices.csv thiếu cột bắt buộc: {', '.join(missing)}"
                )

            has_alias_column = "alias" in reader.fieldnames
            if not has_alias_column:
                logger.warning(
                    "Devices.csv chưa có cột 'alias' — tìm kiếm /checktd sẽ chỉ khớp theo "
                    "hostname. Thêm cột 'alias' (không bắt buộc) nếu cần tìm theo tên gợi ý."
                )

            devices: dict[str, Device] = {}
            for row_num, row in enumerate(reader, start=2):
                hostname = (row.get("hostname") or "").strip()
                if not hostname:
                    logger.warning("Bỏ qua dòng %d trong Devices.csv: thiếu hostname", row_num)
                    continue

                device = Device(
                    hostname=hostname,
                    management_ip=(row.get("management_ip") or "").strip(),
                    vendor=(row.get("vendor") or "").strip(),
                    model=(row.get("model") or "").strip(),
                    role=(row.get("role") or "").strip(),
                    province=(row.get("province") or "").strip(),
                    ssh_user=(row.get("ssh_user") or "").strip(),
                    description=(row.get("description") or "").strip(),
                    key_type=(row.get("key_type") or "").strip(),
                    alias=(row.get("alias") or "").strip() if has_alias_column else "",
                )

                if hostname in devices:
                    logger.warning(
                        "Hostname trùng lặp trong Devices.csv: %s (dòng %d, ghi đè bản ghi trước)",
                        hostname,
                        row_num,
                    )
                devices[hostname] = device

        with self._lock:
            self._devices_by_hostname = devices

        logger.info("Đã nạp %d thiết bị từ %s", len(devices), self._csv_path)

    def reload(self) -> None:
        """Nạp lại Devices.csv từ đĩa (dùng khi file được cập nhật)."""
        self._load()

    def get_device(self, hostname: str) -> Device | None:
        """Trả về Device nếu tồn tại, ngược lại trả về None."""
        with self._lock:
            return self._devices_by_hostname.get(hostname.strip())

    def search_devices(self, query: str) -> list[Device]:
        """
        Tìm thiết bị theo tên gợi ý, khớp KHÔNG phân biệt hoa/thường, dạng
        chứa chuỗi con (substring), trên CẢ hai cột: hostname VÀ alias.

        Trả về danh sách Device khớp, sắp xếp theo hostname để hiển thị ổn
        định. Query rỗng trả về danh sách rỗng (không liệt kê toàn bộ).
        """
        q = query.strip().lower()
        if not q:
            return []

        with self._lock:
            devices = list(self._devices_by_hostname.values())

        matches = [
            device
            for device in devices
            if q in device.hostname.lower()
            or any(q in alias.lower() for alias in device.alias_list())
        ]
        matches.sort(key=lambda d: d.hostname.lower())
        return matches
