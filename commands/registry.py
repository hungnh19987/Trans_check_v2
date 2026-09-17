"""Vendor command registry."""

from __future__ import annotations


class CommandNotFoundError(RuntimeError):
    """Không tìm được command phù hợp cho function/vendor/model."""


_VENDOR_MODEL_COMMANDS: dict[tuple[str, str, str], str] = {}

_VENDOR_COMMANDS: dict[tuple[str, str], str] = {
    ("checktd", "Juniper"): "show interfaces descriptions",
    ("checktd", "Cisco"): "show interfaces description",
    ("checktd", "Ciena"): "port show status",
    ("checktd_optics", "Juniper"): "show interfaces diagnostics optics {interface}",
    ("checktd_optics", "Cisco"): "show interface transceiver",
    ("checktd_optics", "Ciena"): "port xcvr show port {interface}",
}

_DEFAULT_COMMANDS: dict[str, str] = {}


class CommandRegistry:
    """Tra cứu CLI command theo function + vendor + model."""

    def get_command(self, function: str, vendor: str, model: str) -> str:
        key_exact = (function, vendor, model)
        if key_exact in _VENDOR_MODEL_COMMANDS:
            return _VENDOR_MODEL_COMMANDS[key_exact]
        key_vendor = (function, vendor)
        if key_vendor in _VENDOR_COMMANDS:
            return _VENDOR_COMMANDS[key_vendor]
        if function in _DEFAULT_COMMANDS:
            return _DEFAULT_COMMANDS[function]
        raise CommandNotFoundError(
            f"Không tìm thấy command cho function='{function}', vendor='{vendor}', model='{model}'."
        )
