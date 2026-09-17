"""Parser for Juniper optical diagnostics output."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class JuniperOptics:
    output_power: str
    rx_power: str
    rx_high_alarm_threshold: str
    rx_low_warning_threshold: str


_VALUE_RE = r"([+-]?\d+(?:\.\d+)?)\s*dBm"


def _extract_dbm(raw_output: str, label_pattern: str) -> str | None:
    match = re.search(
        rf"^\s*{label_pattern}\s*:\s*[^\n]*?/\s*{_VALUE_RE}",
        raw_output,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return match.group(1) if match else None


def parse_juniper_optics(raw_output: str) -> JuniperOptics | None:
    """Extract the four optical values required by the Telegram response."""
    output_power = _extract_dbm(raw_output, r"Laser\s+output\s+power")
    rx_power = _extract_dbm(raw_output, r"Laser\s+(?:rx|receiver)\s+power")
    rx_high_alarm = _extract_dbm(
        raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+high\s+alarm\s+threshold"
    )
    # The requested Telegram format calls this the low alarm threshold, while
    # the Juniper output provides the requested -26.99 dBm value as the low
    # warning threshold (the actual low alarm value is -27.96 dBm).
    rx_low_warning = _extract_dbm(
        raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+low\s+warning\s+threshold"
    )

    if None in (output_power, rx_power, rx_high_alarm, rx_low_warning):
        return None

    return JuniperOptics(
        output_power=output_power,
        rx_power=rx_power,
        rx_high_alarm_threshold=rx_high_alarm,
        rx_low_warning_threshold=rx_low_warning,
    )
