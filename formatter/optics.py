"""Telegram formatting for optical diagnostics."""

from __future__ import annotations

import html

from device.models import Device
from parser.optics import JuniperOptics


def format_juniper_optics(device: Device, interface: str, optics: JuniperOptics) -> str:
    """Render the Juniper optical values as one copy-friendly code block."""
    text = (
        f"Thiết bị: {device.hostname}\n"
        f"Cổng: {interface}\n"
        f"Laser output power: {optics.output_power} dBm\n"
        f"Laser rx power: {optics.rx_power} dBm\n"
        f"Laser rx power high alarm threshold: {optics.rx_high_alarm_threshold} dBm\n"
        f"Laser rx power low alarm threshold: {optics.rx_low_warning_threshold} dBm"
    )
    return f"<pre>{html.escape(text)}</pre>"
