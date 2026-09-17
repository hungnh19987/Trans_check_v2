"""Parsers for vendor optical diagnostics output."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class JuniperOptics:
    output_power: str
    rx_power: str
    rx_high_alarm_threshold: str
    rx_low_alarm_threshold: str
    rx_high_warning_threshold: str
    rx_low_warning_threshold: str


@dataclass(frozen=True)
class CiscoTransceiver:
    temperature: str
    voltage: str
    current: str
    tx_power: str
    rx_power: str


_VALUE_RE = r"([+-]?\d+(?:\.\d+)?)\s*dBm"


def _extract_dbm(raw_output: str, label_pattern: str) -> str | None:
    match = re.search(
        rf"^\s*{label_pattern}\s*:\s*[^\n]*?/\s*{_VALUE_RE}",
        raw_output,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return match.group(1) if match else None


def parse_juniper_optics(raw_output: str) -> JuniperOptics | None:
    """Extract current power and all Juniper RX alarm/warning thresholds."""
    values = {
        "output_power": _extract_dbm(raw_output, r"Laser\s+output\s+power"),
        "rx_power": _extract_dbm(raw_output, r"Laser\s+(?:rx|receiver)\s+power"),
        "rx_high_alarm_threshold": _extract_dbm(
            raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+high\s+alarm\s+threshold"
        ),
        "rx_low_alarm_threshold": _extract_dbm(
            raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+low\s+alarm\s+threshold"
        ),
        "rx_high_warning_threshold": _extract_dbm(
            raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+high\s+warning\s+threshold"
        ),
        "rx_low_warning_threshold": _extract_dbm(
            raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+low\s+warning\s+threshold"
        ),
    }
    if any(value is None for value in values.values()):
        return None
    return JuniperOptics(**values)  # type: ignore[arg-type]


_CISCO_ROW_RE = re.compile(
    r"^\s*(?P<port>\S+)\s+"
    r"(?P<temperature>\S+)\s+"
    r"(?P<voltage>\S+)\s+"
    r"(?P<current>\S+)\s+"
    r"(?P<tx_power>\S+)\s+"
    r"(?P<rx_power>\S+)\s*$"
)


def parse_cisco_transceiver(raw_output: str, interface: str) -> CiscoTransceiver | None:
    """Parse the requested Cisco row from ``show interface transceiver``."""
    for line in raw_output.splitlines():
        match = _CISCO_ROW_RE.match(line)
        if match and match.group("port") == interface:
            values = match.groupdict()
            values.pop("port")
            return CiscoTransceiver(**values)
    return None
