"""Cấu trúc kết quả chung trả về từ SSH Gateway / xuyên suốt pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    NMS_CONNECTION_FAILED = "NMS_CONNECTION_FAILED"
    DEVICE_CONNECTION_FAILED = "DEVICE_CONNECTION_FAILED"
    COMMAND_FAILED = "COMMAND_FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class CommandResult:
    status: ResultStatus
    device: str | None = None
    vendor: str | None = None
    model: str | None = None
    command: str | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration: float = 0.0
    error: str | None = None
