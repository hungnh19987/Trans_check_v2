"""
Command Registry.

Ánh xạ: (function, vendor, model) -> CLI command thực thi trên thiết bị.

Thứ tự fallback khi tra cứu:
    1. Vendor + Model + Function   (chính xác nhất)
    2. Vendor + Function           (áp dụng chung cho vendor)
    3. Default (nếu function có định nghĩa mặc định)

Không hard-code command trong Handler — Handler chỉ gọi
`CommandRegistry.get_command(function, vendor, model)`.

V1 chỉ định nghĩa command cho function "checktd" (show interface description),
theo đúng phạm vi yêu cầu. Command cho vendor/model khác cần được bổ sung vào
_VENDOR_MODEL_COMMANDS / _VENDOR_COMMANDS / _DEFAULT_COMMANDS khi triển khai
cho thiết bị thực tế — registry không tự suy đoán command cho vendor không
được đặc tả.
"""

from __future__ import annotations


class CommandNotFoundError(RuntimeError):
    """Không tìm được command phù hợp cho function/vendor/model."""


# Key: (function, vendor, model) -> command
_VENDOR_MODEL_COMMANDS: dict[tuple[str, str, str], str] = {
    # Ví dụ: ("checktd", "Juniper", "ACX2100"): "show interface description",
}

# Key: (function, vendor) -> command
_VENDOR_COMMANDS: dict[tuple[str, str], str] = {
    ("checktd", "Juniper"): "show interfaces descriptions",
    ("checktd", "Cisco"): "show interfaces description",
    ("checktd", "Ciena"): "port show status",
}

# Key: function -> command mặc định khi không khớp vendor/model nào ở trên
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
            f"Không tìm thấy command cho function='{function}', "
            f"vendor='{vendor}', model='{model}'. "
            "Cần bổ sung ánh xạ trong commands/registry.py."
        )
