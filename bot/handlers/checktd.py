"""
CheckTDHandler.

Luồng xử lý MỚI cho /checktd:

    /checktd "tên gợi ý"
        -> Validate Group
        -> Tìm kiếm trong Devices.csv (cột hostname VÀ alias)
        -> Không có kết quả -> báo không tìm thấy
        -> Có kết quả -> hiển thị danh sách hostname dưới dạng NÚT BẤM
              (inline keyboard)

    Người dùng bấm nút chọn hostname
        -> CommandRegistry.get_command()
        -> SSH Gateway (Wyse -> NMS -> Device)
        -> Parser
        -> Formatter
        -> Telegram (edit tin nhắn để hiển thị kết quả)

Handler KHÔNG tự đọc CSV, KHÔNG tự mở SSH, KHÔNG hard-code command.
"""

from __future__ import annotations

import asyncio
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.guard import is_allowed_chat
from commands.registry import CommandNotFoundError, CommandRegistry
from device.repository import DeviceRepository
from formatter.telegram import format_checktd_success_pages, format_error
from parser.interface import (
    filter_physical_interfaces,
    parse_ciena_interface_description,
    parse_interface_description,
)
from ssh.gateway import SSHGateway
from ssh.result import CommandResult, ResultStatus

logger = logging.getLogger("td_bot.checktd")

FUNCTION_NAME = "checktd"

# Giới hạn số nút bấm hiển thị trong 1 lần tìm kiếm, để tránh danh sách quá
# dài / vượt giới hạn kích thước tin nhắn của Telegram.
_MAX_SEARCH_RESULTS = 20

# Tiền tố callback_data cho nút chọn thiết bị, theo sau là chỉ số (index)
# trong danh sách kết quả tìm kiếm gần nhất của group đó — KHÔNG nhúng
# thẳng hostname vào callback_data (giới hạn 64 byte của Telegram, và
# hostname có thể dài/chứa ký tự đặc biệt).
_CALLBACK_PREFIX = "checktd"

# Key lưu danh sách kết quả tìm kiếm gần nhất trong context.chat_data.
_CHAT_DATA_CANDIDATES_KEY = "checktd_candidates"


class CheckTDHandler:
    def __init__(
        self,
        allowed_group_id: int,
        device_repository: DeviceRepository,
        command_registry: CommandRegistry,
        ssh_gateway: SSHGateway,
    ) -> None:
        self._allowed_group_id = allowed_group_id
        self._device_repository = device_repository
        self._command_registry = command_registry
        self._ssh_gateway = ssh_gateway

    # ------------------------------------------------------------------
    # Bước 1: /checktd "tên gợi ý" -> tìm kiếm, hiển thị nút bấm
    # ------------------------------------------------------------------
    async def handle_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed_chat(update, self._allowed_group_id):
            # Không xử lý, không phản hồi cho group không được phép.
            return

        message = update.effective_message

        args = context.args or []
        query_text = " ".join(args).strip().strip('"')
        if not query_text:
            await message.reply_text(
                'Cú pháp: /checktd "tên gợi ý"\nVí dụ: /checktd DIEN_CHAU'
            )
            return

        matches = self._device_repository.search_devices(query_text)
        if not matches:
            await message.reply_text(f'Không tìm thấy thiết bị nào khớp với "{query_text}".')
            return

        truncated = len(matches) > _MAX_SEARCH_RESULTS
        shown = matches[:_MAX_SEARCH_RESULTS]

        # Lưu danh sách kết quả (theo chat) để tra lại khi người dùng bấm
        # nút. Lưu ý V1: mỗi chat chỉ giữ MỘT danh sách kết quả gần nhất —
        # tìm kiếm mới sẽ ghi đè danh sách cũ trong cùng group.
        context.chat_data[_CHAT_DATA_CANDIDATES_KEY] = {
            str(idx): device.hostname for idx, device in enumerate(shown)
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    device.hostname, callback_data=f"{_CALLBACK_PREFIX}:{idx}"
                )
            ]
            for idx, device in enumerate(shown)
        ]

        text = f'🔎 Tìm thấy {len(matches)} thiết bị khớp với "{query_text}"'
        if truncated:
            text += (
                f" (chỉ hiển thị {_MAX_SEARCH_RESULTS} kết quả đầu — "
                "gõ tên cụ thể hơn để thu hẹp)"
            )
        text += ":"

        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # ------------------------------------------------------------------
    # Bước 2: người dùng bấm nút -> thực hiện kiểm tra thiết bị đã chọn
    # ------------------------------------------------------------------
    async def handle_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return

        if not is_allowed_chat(update, self._allowed_group_id):
            await callback_query.answer()
            return

        # BẮT BUỘC trả lời callback_query để Telegram tắt trạng thái loading
        # trên nút, kể cả khi phiên chọn đã hết hạn.
        await callback_query.answer()

        data = callback_query.data or ""
        idx = data.split(":", 1)[1] if ":" in data else ""

        candidates: dict[str, str] = context.chat_data.get(_CHAT_DATA_CANDIDATES_KEY) or {}
        hostname = candidates.get(idx)

        if hostname is None:
            await callback_query.edit_message_text(
                "Phiên chọn đã hết hạn hoặc không còn hợp lệ (có thể do đã tìm kiếm mới). "
                'Vui lòng gõ lại /checktd "tên gợi ý".'
            )
            return

        await callback_query.edit_message_text(f"🔎 Đang kiểm tra {hostname} ...")

        pages = await self._check_device(hostname)

        first_page, *rest_pages = pages
        await callback_query.edit_message_text(first_page, parse_mode=ParseMode.HTML)
        for page_text in rest_pages:
            await callback_query.message.reply_text(page_text, parse_mode=ParseMode.HTML)

    # ------------------------------------------------------------------
    # Logic kiểm tra thiết bị dùng chung, trả về danh sách tin nhắn (HTML)
    # để bên gọi tự quyết định gửi/hiển thị (reply_text hay edit_message_text).
    # ------------------------------------------------------------------
    async def _check_device(self, hostname: str) -> list[str]:
        started = time.monotonic()

        # 3. Tìm thiết bị trong Devices.csv (qua Repository).
        device = self._device_repository.get_device(hostname)
        if device is None:
            logger.info("checktd: device not found | hostname=%s", hostname)
            return [
                format_error(
                    "KHÔNG THỂ KIỂM TRA THIẾT BỊ", hostname, ResultStatus.DEVICE_NOT_FOUND
                )
            ]

        # 4. Xác định command phù hợp qua Command Registry.
        try:
            command = self._command_registry.get_command(
                FUNCTION_NAME, device.vendor, device.model
            )
        except CommandNotFoundError as exc:
            logger.error(
                "checktd: command not found | hostname=%s vendor=%s model=%s error=%s",
                hostname,
                device.vendor,
                device.model,
                exc,
            )
            return [
                format_error("KHÔNG THỂ KIỂM TRA THIẾT BỊ", hostname, ResultStatus.UNKNOWN_ERROR)
            ]

        # 5-8. SSH Wyse -> NMS -> Device, thực thi command, thu kết quả.
        #
        # QUAN TRỌNG: run_device_command() là hàm BLOCKING (paramiko, I/O
        # đồng bộ). Phải chạy trong thread riêng bằng asyncio.to_thread —
        # nếu gọi trực tiếp (await ngay trên event loop), một khi SSH bị
        # treo thì TOÀN BỘ bot sẽ đứng hình theo.
        result: CommandResult = await asyncio.to_thread(
            self._ssh_gateway.run_device_command,
            hostname,
            command,
            device.key_type,
            device.vendor,
        )
        result.device = device.hostname
        result.vendor = device.vendor
        result.model = device.model

        duration_total = time.monotonic() - started

        # 12. Ghi log (không log credential).
        logger.info(
            "checktd | hostname=%s vendor=%s model=%s status=%s duration=%.2fs error=%s",
            hostname,
            device.vendor,
            device.model,
            result.status.value,
            duration_total,
            result.error or "-",
        )

        # Log riêng stdout/stderr THÔ ở mức DEBUG khi không thành công, để
        # troubleshoot (ssh error message thường không chứa credential, chỉ
        # là text lỗi kết nối/permission — an toàn để log). Bật bằng cách
        # đặt LOG_LEVEL=DEBUG trong .env khi cần chẩn đoán, rồi trả lại INFO
        # sau khi xong.
        if result.status != ResultStatus.SUCCESS:
            logger.debug(
                "checktd raw ssh output | hostname=%s exit_code=%s command=%r\n"
                "--- stdout ---\n%s\n--- stderr ---\n%s",
                hostname,
                result.exit_code,
                result.command,
                result.stdout.strip() or "(rỗng)",
                result.stderr.strip() or "(rỗng)",
            )

        # 9-10. Parse + Format.
        if result.status != ResultStatus.SUCCESS:
            return [format_error("KHÔNG THỂ KIỂM TRA THIẾT BỊ", hostname, result.status)]

        # Parser dùng chung cho các vendor có cùng cấu trúc bảng 4 cột
        # (interface, admin/status, link/protocol, description) — hiện tại
        # là Juniper và Cisco. Nếu output không đúng cấu trúc này (vendor
        # khác chưa hỗ trợ), tự fallback về raw output.
        interface_rows = None
        if device.vendor.strip().lower() == "ciena":
            parsed = parse_ciena_interface_description(result.stdout)
        else:
            parsed = parse_interface_description(result.stdout)
        if parsed is not None:
            # Chỉ hiển thị interface vật lý, bỏ sub-interface (dạng
            # ge-1/2/1.102 / Gi0/0/1.100) để kết quả ngắn gọn hơn.
            interface_rows = filter_physical_interfaces(parsed)

        return format_checktd_success_pages(device, result, interface_rows)
