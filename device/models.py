"""Model dữ liệu cho thiết bị, ánh xạ đúng các cột trong Devices.csv."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    hostname: str
    management_ip: str
    vendor: str
    model: str
    role: str
    province: str
    ssh_user: str
    description: str
    key_type: str
    alias: str = ""  # danh sách alias phân tách bằng dấu ";", dùng để tìm kiếm

    def alias_list(self) -> list[str]:
        """Tách chuỗi alias (phân tách bằng ';') thành danh sách, đã strip."""
        if not self.alias:
            return []
        return [a.strip() for a in self.alias.split(";") if a.strip()]
