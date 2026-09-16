"""
Parser cho command kiểm tra trạng thái interface.

Tách biệt hoàn toàn khỏi SSH: SSH Gateway chỉ lấy raw output, Parser chuyển
raw output đó thành dữ liệu có cấu trúc (interface, admin_status,
oper_status, description).

V1: hiện thực một parser dùng chung cho các output dạng bảng 4 cột
(interface, trạng thái admin, trạng thái link, description), cùng một parser
riêng cho bảng pipe-delimited của Ciena:

    Juniper (`show interface description`):
        Interface       Admin Link Description
        ge-0/0/0        up    up   CORE-01

    Cisco (`show interfaces description`):
        Interface                      Status         Protocol Description
        Gi0/0/0                        up             up       TO_SITE_A

    Ciena (`show interface description`):
        ## | Description | Link | ...
        1  | TO_SITE_A   | Up   | ...

Nếu output không đúng định dạng mong đợi (không nhận diện được dòng
header), trả về None để Formatter tự quyết định hiển thị raw output thay vì
cố parse sai.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Các từ khoá header được chấp nhận cho cột thứ 2 (admin/status) — chỉ cần
# nhận diện được "interface" + một trong các từ này là đủ xác định đây là
# bảng 4 cột theo đúng cấu trúc trên.
_ADMIN_HEADER_KEYWORDS = ("admin", "status")


@dataclass
class InterfaceRow:
    interface: str
    admin_status: str
    oper_status: str
    description: str


def parse_interface_description(raw_output: str) -> list[InterfaceRow] | None:
    """
    Parse output dạng bảng 4 cột (interface, admin/status, link/protocol,
    description), dùng chung cho Juniper và Cisco vì cùng cấu trúc cột.

    Trả về None nếu không nhận diện được header, để caller fallback về raw
    output thay vì hiển thị dữ liệu parse sai.
    """
    lines = [line for line in raw_output.splitlines() if line.strip()]
    if not lines:
        return None

    header_idx = None
    for idx, line in enumerate(lines):
        lowered = line.lower()
        if "interface" in lowered and any(kw in lowered for kw in _ADMIN_HEADER_KEYWORDS):
            header_idx = idx
            break

    if header_idx is None:
        return None

    rows: list[InterfaceRow] = []
    for line in lines[header_idx + 1 :]:
        parts = line.split()
        if len(parts) < 3:
            continue

        interface, admin_status, oper_status = parts[0], parts[1], parts[2]
        description = " ".join(parts[3:]) if len(parts) > 3 else ""

        rows.append(
            InterfaceRow(
                interface=interface,
                admin_status=admin_status,
                oper_status=oper_status,
                description=description,
            )
        )

    return rows or None


def parse_ciena_interface_description(raw_output: str) -> list[InterfaceRow] | None:
    """
    Parse output ``show interface description`` của Ciena.

    Ciena trả về bảng pipe-delimited chỉ có ``Link State`` thay vì admin và
    oper status riêng. Số cổng trong cột ``##`` được dùng làm tên interface;
    các dòng tiếp theo có cột ``##`` rỗng là phần nối của description.
    """
    lines = [line for line in raw_output.splitlines() if line.strip()]
    if not lines or not any("port operational status" in line.lower() for line in lines):
        return None

    rows: list[InterfaceRow] = []
    for line in lines:
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if len(fields) < 3:
            continue

        port_number = fields[0]
        description = fields[1]
        link_state = fields[2].lower()

        if re.fullmatch(r"\d+", port_number):
            rows.append(
                InterfaceRow(
                    interface=port_number,
                    admin_status=link_state,
                    oper_status=link_state,
                    description=description,
                )
            )
        elif not port_number and description and rows:
            rows[-1].description = f"{rows[-1].description}{description}"

    return rows or None


def filter_physical_interfaces(rows: list[InterfaceRow]) -> list[InterfaceRow]:
    """
    Chỉ giữ lại interface vật lý, bỏ các sub-interface (dạng có dấu "."
    trong tên, ví dụ ge-1/2/1.102 hoặc Gi0/0/1.100), để kết quả hiển thị
    ngắn gọn hơn.
    """
    return [r for r in rows if "." not in r.interface]
