"""Telegram formatting for vendor optical diagnostics."""

from __future__ import annotations

import html

from device.models import Device
from parser.optics import CiscoTransceiver, JuniperOptics


def _code_block(text: str) -> str:
    return f"<pre>{html.escape(text)}</pre>"


def format_juniper_optics(device: Device, interface: str, optics: JuniperOptics) -> str:
    text = (
        f"Thiết bị: {device.hostname}\n"
        f"Cổng: {interface}\n"
        f"Laser output power: {optics.output_power} dBm\n"
        f"Laser rx power: {optics.rx_power} dBm\n"
        f"Laser rx power high alarm threshold: {optics.rx_high_alarm_threshold} dBm\n"
        f"Laser rx power low alarm threshold: {optics.rx_low_alarm_threshold} dBm\n"
        f"Laser rx power high warning threshold: {optics.rx_high_warning_threshold} dBm\n"
        f"Laser rx power low warning threshold: {optics.rx_low_warning_threshold} dBm"
    )
    return _code_block(text)


def format_cisco_transceiver(
    device: Device, interface: str, transceiver: CiscoTransceiver
) -> str:
    text = (
        f"Tên thiết bị: {device.hostname}\n"
        f"Cổng: {interface}\n\n"
        f"Temperature (Celsius): {transceiver.temperature}\n"
        f"Voltage (Volts): {transceiver.voltage}\n"
        f"Current (mA): {transceiver.current}\n"
        f"Optical Tx Power (dBm): {transceiver.tx_power}\n"
        f"Optical Rx Power (dBm): {transceiver.rx_power}"
    )
    return _code_block(text)
