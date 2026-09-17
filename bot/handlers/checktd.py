"""Telegram handler for device and optical checks."""

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
from formatter.optics import format_ciena_optics, format_cisco_transceiver, format_juniper_optics
from formatter.telegram import format_checktd_success_pages, format_error
from parser.interface import filter_physical_interfaces, parse_ciena_interface_description, parse_interface_description
from parser.optics import parse_ciena_optics, parse_cisco_transceiver, parse_juniper_optics
from ssh.gateway import SSHGateway
from ssh.result import CommandResult, ResultStatus

logger = logging.getLogger("td_bot.checktd")
FUNCTION_NAME = "checktd"
OPTICS_FUNCTION_NAME = "checktd_optics"
_MAX_SEARCH_RESULTS = 20
_CALLBACK_PREFIX = "checktd"
_CHAT_DATA_CANDIDATES_KEY = "checktd_candidates"


class CheckTDHandler:
    def __init__(self, allowed_group_id: int, device_repository: DeviceRepository, command_registry: CommandRegistry, ssh_gateway: SSHGateway) -> None:
        self._allowed_group_id = allowed_group_id
        self._device_repository = device_repository
        self._command_registry = command_registry
        self._ssh_gateway = ssh_gateway

    async def handle_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed_chat(update, self._allowed_group_id):
            return
        message = update.effective_message
        args = context.args or []
        if len(args) >= 2:
            if len(args) != 2:
                await message.reply_text("Cú pháp: /checktd <hostname> <interface>\nVí dụ: /checktd AGG-1.1-NANDCU11 xe-1/0/1")
                return
            hostname, interface = args
            await message.reply_text(f"🔎 Đang kiểm tra quang {hostname} {interface} ...")
            result = await self._check_optical_device(hostname, interface)
            await message.reply_text(result, parse_mode=ParseMode.HTML)
            return

        query_text = " ".join(args).strip().strip('"')
        if not query_text:
            await message.reply_text('Cú pháp: /checktd <hostname> <interface>\nVí dụ: /checktd AGG-1.1-NANDCU11 xe-1/0/1\n\nHoặc dùng /checktd "tên gợi ý" để tìm thiết bị.')
            return
        matches = self._device_repository.search_devices(query_text)
        if not matches:
            await message.reply_text(f'Không tìm thấy thiết bị nào khớp với "{query_text}".')
            return
        shown = matches[:_MAX_SEARCH_RESULTS]
        context.chat_data[_CHAT_DATA_CANDIDATES_KEY] = {str(idx): device.hostname for idx, device in enumerate(shown)}
        keyboard = [[InlineKeyboardButton(device.hostname, callback_data=f"{_CALLBACK_PREFIX}:{idx}")] for idx, device in enumerate(shown)]
        text = f'🔎 Tìm thấy {len(matches)} thiết bị khớp với "{query_text}"'
        if len(matches) > _MAX_SEARCH_RESULTS:
            text += f" (chỉ hiển thị {_MAX_SEARCH_RESULTS} kết quả đầu — gõ tên cụ thể hơn để thu hẹp)"
        await message.reply_text(text + ":", reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        if not is_allowed_chat(update, self._allowed_group_id):
            await callback_query.answer()
            return
        await callback_query.answer()
        data = callback_query.data or ""
        idx = data.split(":", 1)[1] if ":" in data else ""
        candidates: dict[str, str] = context.chat_data.get(_CHAT_DATA_CANDIDATES_KEY) or {}
        hostname = candidates.get(idx)
        if hostname is None:
            await callback_query.edit_message_text("Phiên chọn đã hết hạn hoặc không còn hợp lệ. Vui lòng gõ lại /checktd \"tên gợi ý\".")
            return
        await callback_query.edit_message_text(f"🔎 Đang kiểm tra {hostname} ...")
        pages = await self._check_device(hostname)
        first_page, *rest_pages = pages
        await callback_query.edit_message_text(first_page, parse_mode=ParseMode.HTML)
        for page_text in rest_pages:
            await callback_query.message.reply_text(page_text, parse_mode=ParseMode.HTML)

    async def _check_optical_device(self, hostname: str, interface: str) -> str:
        started = time.monotonic()
        device = self._device_repository.get_device(hostname)
        if device is None:
            return format_error("KHÔNG THỂ KIỂM TRA QUANG", hostname, ResultStatus.DEVICE_NOT_FOUND)
        vendor = device.vendor.strip().lower()
        if vendor not in {"juniper", "cisco", "ciena"}:
            return format_error("KHÔNG THỂ KIỂM TRA QUANG", hostname, ResultStatus.UNKNOWN_ERROR)
        try:
            template = self._command_registry.get_command(OPTICS_FUNCTION_NAME, device.vendor, device.model)
        except CommandNotFoundError:
            return format_error("KHÔNG THỂ KIỂM TRA QUANG", hostname, ResultStatus.UNKNOWN_ERROR)
        command = template.format(interface=interface)
        result: CommandResult = await asyncio.to_thread(self._ssh_gateway.run_device_command, hostname, command, device.key_type, device.vendor)
        result.device, result.vendor, result.model = device.hostname, device.vendor, device.model
        logger.info("checktd optics | hostname=%s interface=%s vendor=%s status=%s duration=%.2fs", hostname, interface, device.vendor, result.status.value, time.monotonic() - started)
        if result.status != ResultStatus.SUCCESS:
            return format_error("KHÔNG THỂ KIỂM TRA QUANG", hostname, result.status)
        if vendor == "juniper":
            optics = parse_juniper_optics(result.stdout)
            return format_juniper_optics(device, interface, optics) if optics else format_error("KHÔNG THỂ KIỂM TRA QUANG", hostname, ResultStatus.COMMAND_FAILED)
        if vendor == "cisco":
            optics = parse_cisco_transceiver(result.stdout, interface)
            return format_cisco_transceiver(device, interface, optics) if optics else format_error("KHÔNG THỂ KIỂM TRA QUANG", hostname, ResultStatus.COMMAND_FAILED)
        optics = parse_ciena_optics(result.stdout)
        return format_ciena_optics(device, interface, optics) if optics else format_error("KHÔNG THỂ KIỂM TRA QUANG", hostname, ResultStatus.COMMAND_FAILED)

    async def _check_device(self, hostname: str) -> list[str]:
        started = time.monotonic()
        device = self._device_repository.get_device(hostname)
        if device is None:
            return [format_error("KHÔNG THỂ KIỂM TRA THIẾT BỊ", hostname, ResultStatus.DEVICE_NOT_FOUND)]
        try:
            command = self._command_registry.get_command(FUNCTION_NAME, device.vendor, device.model)
        except CommandNotFoundError:
            return [format_error("KHÔNG THỂ KIỂM TRA THIẾT BỊ", hostname, ResultStatus.UNKNOWN_ERROR)]
        result: CommandResult = await asyncio.to_thread(self._ssh_gateway.run_device_command, hostname, command, device.key_type, device.vendor)
        result.device, result.vendor, result.model = device.hostname, device.vendor, device.model
        logger.info("checktd | hostname=%s vendor=%s model=%s status=%s duration=%.2fs error=%s", hostname, device.vendor, device.model, result.status.value, time.monotonic() - started, result.error or "-")
        if result.status != ResultStatus.SUCCESS:
            return [format_error("KHÔNG THỂ KIỂM TRA THIẾT BỊ", hostname, result.status)]
        parsed = parse_ciena_interface_description(result.stdout) if device.vendor.strip().lower() == "ciena" else parse_interface_description(result.stdout)
        interface_rows = filter_physical_interfaces(parsed) if parsed is not None else None
        return format_checktd_success_pages(device, result, interface_rows)
