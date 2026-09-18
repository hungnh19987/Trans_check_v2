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


@dataclass(frozen=True)
class CienaOptics:
    rx_power: str
    rx_low_alarm_threshold: str
    rx_high_alarm_threshold: str
    rx_high_warning_threshold: str
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
    values = {
        "output_power": _extract_dbm(raw_output, r"Laser\s+output\s+power"),
        "rx_power": _extract_dbm(raw_output, r"Laser\s+(?:rx|receiver)\s+power"),
        "rx_high_alarm_threshold": _extract_dbm(raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+high\s+alarm\s+threshold"),
        "rx_low_alarm_threshold": _extract_dbm(raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+low\s+alarm\s+threshold"),
        "rx_high_warning_threshold": _extract_dbm(raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+high\s+warning\s+threshold"),
        "rx_low_warning_threshold": _extract_dbm(raw_output, r"Laser\s+(?:rx|receiver)\s+power\s+low\s+warning\s+threshold"),
    }
    if any(value is None for value in values.values()):
        return None
    return JuniperOptics(**values)  # type: ignore[arg-type]


_CISCO_ROW_RE = re.compile(
    r"^\s*(?P<port>\S+)\s+(?P<temperature>\S+)\s+(?P<voltage>\S+)\s+"
    r"(?P<current>\S+)\s+(?P<tx_power>\S+)\s+(?P<rx_power>\S+)\s*$"
)


def parse_cisco_transceiver(raw_output: str, interface: str) -> CiscoTransceiver | None:
    for line in raw_output.splitlines():
        match = _CISCO_ROW_RE.match(line)
        if match and match.group("port") == interface:
            values = match.groupdict()
            values.pop("port")
            return CiscoTransceiver(**values)
    return None


def _extract_ciena_diagnostic_row(raw_output: str) -> tuple[str, str, str, str, str] | None:
    """Parse the two physical rows belonging to Rx Power (dBm)."""
    lines = raw_output.splitlines()
    for index, line in enumerate(lines):
        # Do not escape an already-regex label; this accepts spacing variants.
        if not re.search(r"^\s*\|\s*Rx\s+Power\s+\(dBm\)\s*\|", line, re.IGNORECASE):
            continue
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if len(fields) < 5:
            continue
        low_line = lines[index + 1] if index + 1 < len(lines) else ""
        low_fields = [field.strip() for field in low_line.strip().strip("|").split("|")]
        if len(low_fields) < 5:
            continue
        return (
            fields[1],
            re.sub(r"^HIGH\s+", "", fields[2], flags=re.IGNORECASE),
            re.sub(r"^LOW\s+", "", low_fields[2], flags=re.IGNORECASE),
            re.sub(r"^HIGH\s+", "", fields[4], flags=re.IGNORECASE),
            re.sub(r"^LOW\s+", "", low_fields[4], flags=re.IGNORECASE),
        )
    return None


def parse_ciena_optics(raw_output: str) -> CienaOptics | None:
    row = _extract_ciena_diagnostic_row(raw_output)
    if row is None:
        return None
    value, alarm_high, alarm_low, warning_high, warning_low = row
    return CienaOptics(value, alarm_low, alarm_high, warning_high, warning_low)
