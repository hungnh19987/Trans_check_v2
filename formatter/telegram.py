"""
Output Formatter.

Chuyển CommandResult (+ dữ liệu đã parse nếu có) thành text hiển thị trên
Telegram. Không bao giờ hiển thị traceback Python, private key, password
hoặc thông tin xác thực.

Định dạng theo mẫu:

    🔌 LSW_NA_TKY_KY_SON
    🏷 Vendor: <code>Juniper</code>
    ━━━━━━━━━━━━━━━━━━━━

    🟢 <code>Gi0/0/0</code>
       <code>TO_NA_TKY_KY_SON_PO_NA_TY_NoiSite/FO/MBF</code>

Tên thiết bị, vendor, interface và description được bọc trong thẻ HTML
<code> để Telegram hiển thị dạng monospace và cho phép chạm để copy trên
thiết bị di động.
"""

from __future__ import annotations

import html

from device.models import Device
from parser.interface import InterfaceRow
from ssh.result import CommandResult, ResultStatus

_ERROR_MESSAGES: dict[ResultStatus, str] = {
    ResultStatus.DEVICE_NOT_FOUND: "Không tìm thấy thiết bị trong Devices.csv.",
    ResultStatus.NMS_CONNECTION_FAILED: "Không thể kết nối SSH từ hệ thống tới NMS Server.",
    ResultStatus.DEVICE_CONNECTION_FAILED: "Không thể kết nối SSH tới thiết bị.",
    ResultStatus.COMMAND_FAILED: "Thiết bị trả về lỗi khi thực thi command.",
    ResultStatus.TIMEOUT: "Hết thời gian chờ phản hồi.",
    ResultStatus.UNKNOWN_ERROR: "Lỗi không xác định trong quá trình xử lý.",
}

# Giới hạn cứng của Telegram cho một tin nhắn text (bao gồm cả thẻ HTML) là
# 4096 ký tự. Để lại biên an toàn cho phần header/footer và trường hợp
# html.escape() làm chuỗi dài hơn (&, <, > ...).
_TELEGRAM_MAX_LEN = 4096
_CONTENT_MARGIN = 300

_SEPARATOR = "━" * 20


def format_error(title: str, hostname: str, status: ResultStatus) -> str:
    reason = _ERROR_MESSAGES.get(status, "Lỗi không xác định.")
    return (
        f"❌ {html.escape(title)}\n\n"
        f"Thiết bị: <code>{html.escape(hostname)}</code>\n"
        f"Nguyên nhân: {html.escape(reason)}"
    )


def _is_up(row: InterfaceRow) -> bool:
    """Port coi là UP (🟢) chỉ khi CẢ admin và link đều up."""
    return row.admin_status.strip().lower() == "up" and row.oper_status.strip().lower() == "up"


def _build_interface_blocks(rows: list[InterfaceRow]) -> list[list[str]]:
    """
    Mỗi interface -> MỘT khối gồm 1-2 dòng (đã HTML-escape sẵn):
        🟢/🔴 <code>{interface}</code>
           <code>{description}</code> (bỏ dòng này nếu description rỗng)
    """
    blocks: list[list[str]] = []
    for row in rows:
        emoji = "🟢" if _is_up(row) else "🔴"
        line1 = f"{emoji} <code>{html.escape(row.interface)}</code>"
        block = [line1]
        description = row.description.strip()
        if description:
            block.append(f"   <code>{html.escape(description)}</code>")
        blocks.append(block)
    return blocks


def format_checktd_success_pages(
    device: Device,
    result: CommandResult,
    interface_rows: list[InterfaceRow] | None,
) -> list[str]:
    """
    Format kết quả /checktd thành MỘT DANH SÁCH tin nhắn (thường chỉ 1 phần
    tử). Nếu danh sách interface quá dài, tự động chia thành nhiều tin nhắn
    để không vượt quá giới hạn 4096 ký tự/tin nhắn của Telegram.
    """
    hostname_esc = html.escape(device.hostname)
    vendor_esc = html.escape(device.vendor.strip() or "Không xác định")
    header_block = (
        f"🔌 <code>{hostname_esc}</code>\n"
        f"🏷 Vendor: <code>{vendor_esc}</code>\n"
        f"{_SEPARATOR}"
    )

    footer_block: str | None
    wrap_pre: bool

    if interface_rows is not None:
        if interface_rows:
            blocks = _build_interface_blocks(interface_rows)
            up_count = sum(1 for row in interface_rows if _is_up(row))
            down_count = len(interface_rows) - up_count
            footer_block = (
                f"{_SEPARATOR}\n"
                f"📊 Tổng: {len(interface_rows)} port | UP: {up_count} | DOWN: {down_count}"
            )
        else:
            blocks = [["(không có interface vật lý phù hợp)"]]
            footer_block = f"{_SEPARATOR}\n📊 Tổng: 0 port | UP: 0 | DOWN: 0"
        wrap_pre = False
    else:
        # Không parse được -> hiển thị raw output nguyên văn.
        raw_text = result.stdout.strip() or "(không có output)"
        blocks = [[line] for line in (raw_text.splitlines() or [""])]
        footer_block = None
        wrap_pre = True

    def render_body(page_blocks: list[list[str]]) -> str:
        if wrap_pre:
            lines = [line for block in page_blocks for line in block]
            text = "\n".join(lines)
            return f"<pre>{html.escape(text)}</pre>"
        return "\n\n".join("\n".join(block) for block in page_blocks)

    def page_text(page_blocks: list[list[str]], page_idx: int, total_pages: int) -> str:
        if page_idx == 0:
            head = header_block + "\n\n"
        else:
            head = (
                f"🔌 <code>{hostname_esc}</code> "
                f"🏷 <code>{vendor_esc}</code> "
                f"(trang {page_idx + 1}/{total_pages})\n\n"
            )

        body = render_body(page_blocks)
        is_last = page_idx == total_pages - 1
        tail = f"\n\n{footer_block}" if (is_last and footer_block) else ""
        return head + body + tail

    pages_blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    for block in blocks:
        trial = current + [block]
        estimated = len(page_text(trial, page_idx=0, total_pages=1))
        if estimated > _TELEGRAM_MAX_LEN - _CONTENT_MARGIN and current:
            pages_blocks.append(current)
            current = [block]
        else:
            current = trial
    pages_blocks.append(current)

    total_pages = len(pages_blocks)
    return [page_text(page_blocks, idx, total_pages) for idx, page_blocks in enumerate(pages_blocks)]
