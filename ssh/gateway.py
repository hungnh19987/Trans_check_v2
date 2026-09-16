"""
SSH Gateway.

Module DUY NHẤT chịu trách nhiệm về SSH trong toàn bộ ứng dụng.

Luồng:
    Wyse --SSH--> NMS Server --SSH (dùng ~/.ssh/config.devices)--> Device

Cách hiện thực V1:
    - Mở MỘT kết nối SSH (paramiko) từ Wyse tới NMS Server.
    - Trên kết nối đó, thực thi một lệnh `ssh -F <config.devices> <hostname> "<command>"`
      để NMS tự SSH tiếp sang thiết bị bằng SSH config/key đã có sẵn trên NMS.
    - Không copy private key từ NMS về Wyse, không lưu key trong source code.
    - Không yêu cầu bot biết password thiết bị (dựa hoàn toàn vào config.devices).

Thiết bị xác thực bằng username/password (không có SSH key, `key_type` thuộc
nhóm được cấu hình là "password-based", mặc định: non/none/password):
    - Vẫn áp dụng nguyên tắc "Bot không được biết password thiết bị". Bot
      KHÔNG lưu, KHÔNG nhận, KHÔNG log password.
    - Password phải được lưu SẴN trên NMS, trong một file riêng biệt cho
      từng thiết bị (do admin NMS tạo thủ công, ngoài phạm vi Devices.csv và
      ngoài phạm vi bot), tại `<DEVICE_PASSWORD_SECRETS_DIR>/<hostname>`.
    - Bot chỉ biết QUY ƯỚC đường dẫn tới file đó (cấu hình qua
      DEVICE_PASSWORD_SECRETS_DIR), không đọc nội dung file — việc đọc và
      cấp password cho ssh hoàn toàn diễn ra trên NMS, thông qua `sshpass -f`.

Handler KHÔNG được tự mở SSH — chỉ được gọi qua SSHGateway.
"""

from __future__ import annotations

import logging
import re
import shlex
import socket
import time

import paramiko

from ssh.result import CommandResult, ResultStatus

logger = logging.getLogger("td_bot.ssh_gateway")

# Các dấu hiệu lỗi thường gặp khi bản thân bước NMS -> Device thất bại
# (khác với lỗi do chính command trên thiết bị trả về non-zero).
_DEVICE_CONNECTION_ERROR_MARKERS = (
    "could not resolve hostname",
    "connection refused",
    "connection timed out",
    "no route to host",
    "permission denied",
    "host key verification failed",
    "ssh: connect to host",
    "operation timed out",
    "network is unreachable",
    "no such file or directory",  # ví dụ: sai đường dẫn config.devices hoặc alias không tồn tại
    "could not resolve",
    "bad configuration",
    # Lỗi đặc thù của sshpass (thiết bị xác thực bằng password):
    "sshpass: command not found",
    "command not found",
    "sshpass:",
)

# Giá trị mặc định của cột `key_type` trong Devices.csv được coi là "thiết
# bị xác thực bằng username/password, không có SSH key". Có thể ghi đè qua
# biến môi trường PASSWORD_KEY_TYPES (danh sách phân tách bằng dấu phẩy).
_DEFAULT_PASSWORD_KEY_TYPES = frozenset({"non", "none", "password"})


class NmsConnectionError(RuntimeError):
    """Lỗi khi Wyse không kết nối được SSH tới NMS."""


class _RemoteTimeout(RuntimeError):
    """Command trên NMS/Device không thoát trong thời gian cho phép."""


_POLL_INTERVAL = 0.2  # giây, chu kỳ kiểm tra channel khi chờ exit status


def _quote_remote_path(path: str) -> str:
    """
    Quote một đường dẫn để đưa vào lệnh shell chạy trên NMS, NHƯNG vẫn giữ
    được tilde-expansion (`~` -> $HOME) của OpenSSH/shell.

    shlex.quote() bọc chuỗi bằng dấu nháy đơn ('...'), mà bên trong nháy đơn
    thì `~` KHÔNG được shell giãn ra — ssh sẽ nhận đúng chuỗi literal
    "~/.ssh/config.devices" và báo "Can't open user config file ...: No such
    file or directory", dù file thực sự tồn tại. Vì vậy nếu path bắt đầu
    bằng "~/" hoặc là "~", thay bằng "$HOME/" rồi bọc bằng dấu nháy kép
    (nháy kép vẫn cho phép $HOME được giãn), thay vì dùng shlex.quote.
    """
    if path == "~":
        expanded = "$HOME"
    elif path.startswith("~/"):
        expanded = "$HOME/" + path[2:]
    else:
        # Không có tilde -> shlex.quote như bình thường là an toàn nhất.
        return shlex.quote(path)

    # Escape các ký tự cần thiết trong ngữ cảnh nháy kép, KHÔNG escape "$"
    # vì cần giữ nguyên để $HOME được shell giãn ra.
    escaped = expanded.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _normalize_vendor_filename(vendor: str) -> str:
    """
    Chuẩn hoá tên vendor thành tên file an toàn: chữ thường, khoảng trắng ->
    "_", chỉ giữ chữ/số/gạch dưới/gạch ngang. Dùng để tra file password
    dùng chung theo vendor, ví dụ "Juniper" -> "juniper".
    """
    v = vendor.strip().lower()
    v = re.sub(r"\s+", "_", v)
    v = re.sub(r"[^a-z0-9_-]", "", v)
    return v or "unknown"


class SSHGateway:
    def __init__(
        self,
        nms_host: str,
        nms_user: str,
        nms_port: int,
        nms_key_path: str | None,
        ssh_config_devices_path: str,
        timeout: int,
        remote_env_source: str | None = None,
        device_password_secrets_dir: str | None = None,
        sshpass_bin: str = "sshpass",
        password_key_types: frozenset[str] | None = None,
    ) -> None:
        self._nms_host = nms_host
        self._nms_user = nms_user
        self._nms_port = nms_port
        self._nms_key_path = nms_key_path
        self._ssh_config_devices_path = ssh_config_devices_path
        self._timeout = timeout
        # Lệnh shell tùy chọn để nạp lại ssh-agent đã unlock sẵn trên NMS
        # trước khi gọi ssh xuống thiết bị, ví dụ (dùng `keychain`):
        #   source ~/.keychain/$(hostname)-sh
        self._remote_env_source = remote_env_source
        # Thư mục trên NMS chứa file password DÙNG CHUNG THEO VENDOR (mỗi
        # file tên = tên vendor đã chuẩn hoá, ví dụ "juniper", "cisco",
        # nội dung = password thuần). File này do admin NMS tạo và quản lý
        # thủ công — bot chỉ tham chiếu đường dẫn, KHÔNG đọc, KHÔNG lưu,
        # KHÔNG log nội dung.
        self._device_password_secrets_dir = device_password_secrets_dir
        self._sshpass_bin = sshpass_bin
        self._password_key_types = password_key_types or _DEFAULT_PASSWORD_KEY_TYPES

    def _is_password_auth(self, key_type: str) -> bool:
        return key_type.strip().lower() in self._password_key_types

    def _build_remote_cmd(
        self, hostname: str, command: str, key_type: str, vendor: str
    ) -> tuple[str, bool]:
        """Trả về (remote_cmd, is_password_auth)."""
        env_prefix = f"{self._remote_env_source}; " if self._remote_env_source else ""
        quoted_config = _quote_remote_path(self._ssh_config_devices_path)
        quoted_hostname = shlex.quote(hostname)
        quoted_command = shlex.quote(command)

        if self._is_password_auth(key_type):
            if not self._device_password_secrets_dir:
                raise ValueError(
                    f"Thiết bị '{hostname}' (vendor='{vendor}') có key_type='{key_type}' "
                    "(xác thực bằng password) nhưng DEVICE_PASSWORD_SECRETS_DIR chưa "
                    "được cấu hình."
                )

            secrets_dir = self._device_password_secrets_dir.rstrip("/")
            vendor_file = _normalize_vendor_filename(vendor)
            secret_path = f"{secrets_dir}/{vendor_file}"
            quoted_secret = _quote_remote_path(secret_path)

            # KHÔNG dùng BatchMode=yes ở đây: BatchMode sẽ vô hiệu hoá luôn
            # cả việc hỏi/nhận password, khiến sshpass không có tác dụng.
            # Thay vào đó giới hạn số lần hỏi password = 1 và tắt hẳn xác
            # thực bằng key, để nếu password sai thì thất bại nhanh thay vì
            # ssh thử lại nhiều lần.
            remote_cmd = (
                f"{env_prefix}"
                f"{self._sshpass_bin} -f {quoted_secret} "
                f"ssh -F {quoted_config} "
                f"-o PubkeyAuthentication=no "
                f"-o PreferredAuthentications=password,keyboard-interactive "
                f"-o NumberOfPasswordPrompts=1 "
                f"-o ConnectTimeout={self._timeout} "
                f"{quoted_hostname} {quoted_command} < /dev/null"
            )
            return remote_cmd, True

        # `< /dev/null`: BẮT BUỘC. Không cấp pty/stdin thật cho lệnh ssh
        # lồng bên trong, nên nếu thiếu dòng này, khi ssh ở NMS cần hỏi
        # passphrase/password, nó sẽ treo vô hạn chờ đọc stdin (không có
        # EOF). Redirect từ /dev/null đảm bảo ssh nhận EOF ngay lập tức
        # và thoát luôn (lỗi) thay vì treo.
        remote_cmd = (
            f"{env_prefix}"
            f"ssh -F {quoted_config} "
            f"-o BatchMode=yes "
            f"-o ConnectTimeout={self._timeout} "
            f"{quoted_hostname} {quoted_command} < /dev/null"
        )
        return remote_cmd, False

    def _connect_nms(self) -> paramiko.SSHClient:
        """Mở kết nối SSH Wyse -> NMS. Ném NmsConnectionError nếu thất bại."""
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

        connect_kwargs = {
            "hostname": self._nms_host,
            "port": self._nms_port,
            "username": self._nms_user,
            "timeout": self._timeout,
            "banner_timeout": self._timeout,
            "auth_timeout": self._timeout,
        }
        if self._nms_key_path:
            connect_kwargs["key_filename"] = self._nms_key_path

        try:
            client.connect(**connect_kwargs)
        except (
            paramiko.AuthenticationException,
            paramiko.SSHException,
            socket.timeout,
            socket.error,
            OSError,
        ) as exc:
            client.close()
            raise NmsConnectionError(f"Không thể SSH từ Wyse tới NMS ({self._nms_host}): {exc}") from exc

        return client

    @staticmethod
    def _wait_for_exit(
        stdout: paramiko.channel.ChannelFile,
        stderr: paramiko.channel.ChannelFile,
        timeout: int,
    ) -> tuple[int, str, str]:
        """
        Chờ command remote kết thúc, với DEADLINE THẬT SỰ.

        Không dùng `channel.recv_exit_status()` trực tiếp: hàm đó chờ trên
        một threading.Event KHÔNG có timeout, nên nếu tiến trình phía bên
        kia không bao giờ thoát (ví dụ ssh lồng bên trong bị treo chờ
        passphrase), nó sẽ chờ vô hạn và làm treo cả bot.

        Ở đây tự poll `exit_status_ready()` theo chu kỳ, có deadline; nếu
        quá hạn mà channel chưa đóng, chủ động đóng channel và raise
        _RemoteTimeout.
        """
        channel = stdout.channel
        deadline = time.monotonic() + timeout

        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []

        while True:
            if channel.recv_ready():
                out_chunks.append(channel.recv(65536))
            if channel.recv_stderr_ready():
                err_chunks.append(channel.recv_stderr(65536))

            if channel.exit_status_ready():
                # Đọc nốt phần dữ liệu còn lại sau khi biết đã có exit status.
                while channel.recv_ready():
                    out_chunks.append(channel.recv(65536))
                while channel.recv_stderr_ready():
                    err_chunks.append(channel.recv_stderr(65536))
                exit_code = channel.recv_exit_status()
                out_text = b"".join(out_chunks).decode("utf-8", errors="replace")
                err_text = b"".join(err_chunks).decode("utf-8", errors="replace")
                return exit_code, out_text, err_text

            if time.monotonic() >= deadline:
                channel.close()
                raise _RemoteTimeout()

            time.sleep(_POLL_INTERVAL)

    def run_device_command(
        self, hostname: str, command: str, key_type: str = "", vendor: str = ""
    ) -> CommandResult:
        """
        Thực thi `command` trên thiết bị `hostname`, đi qua NMS.

        `key_type` lấy từ cột `key_type` trong Devices.csv, dùng để quyết
        định xác thực bằng SSH key (mặc định) hay bằng password
        (`sshpass`, khi key_type thuộc PASSWORD_KEY_TYPES). Khi xác thực
        bằng password, `vendor` (cột `vendor` trong Devices.csv) dùng để
        tra file password DÙNG CHUNG cho cả vendor đó
        (`DEVICE_PASSWORD_SECRETS_DIR/<vendor>`), không phải theo từng
        thiết bị.

        Trả về CommandResult với status/stdout/stderr/exit_code/duration/error.
        Trường device/vendor/model/command do caller (Handler) điền thêm.

        LƯU Ý QUAN TRỌNG: hàm này là BLOCKING (I/O đồng bộ). Bên gọi (Telegram
        handler bất đồng bộ) PHẢI chạy hàm này trong một thread riêng
        (`asyncio.to_thread` / `run_in_executor`), không được `await` gọi
        trực tiếp, nếu không toàn bộ event loop của bot sẽ bị treo theo.
        """
        started = time.monotonic()
        client: paramiko.SSHClient | None = None

        try:
            try:
                remote_cmd, is_password_auth = self._build_remote_cmd(
                    hostname, command, key_type, vendor
                )
            except ValueError as exc:
                logger.error("Config error for %s: %s", hostname, exc)
                return CommandResult(
                    status=ResultStatus.UNKNOWN_ERROR,
                    command=command,
                    duration=time.monotonic() - started,
                    error=str(exc),
                )

            try:
                client = self._connect_nms()
            except NmsConnectionError as exc:
                logger.error("NMS connection failed: %s", exc)
                return CommandResult(
                    status=ResultStatus.NMS_CONNECTION_FAILED,
                    command=command,
                    duration=time.monotonic() - started,
                    error=str(exc),
                )

            try:
                stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=self._timeout)
                stdin.close()
                exit_code, out_text, err_text = self._wait_for_exit(stdout, stderr, self._timeout)
            except socket.timeout:
                return CommandResult(
                    status=ResultStatus.TIMEOUT,
                    command=command,
                    duration=time.monotonic() - started,
                    error=f"Hết thời gian chờ ({self._timeout}s) khi thực thi command trên {hostname}",
                )
            except _RemoteTimeout:
                timeout_hint = (
                    f"kiểm tra file password tại DEVICE_PASSWORD_SECRETS_DIR/"
                    f"{_normalize_vendor_filename(vendor)}"
                    if is_password_auth
                    else "có thể do private key trên NMS cần passphrase/ssh-agent chưa unlock"
                )
                return CommandResult(
                    status=ResultStatus.TIMEOUT,
                    command=command,
                    duration=time.monotonic() - started,
                    error=(
                        f"Hết thời gian chờ ({self._timeout}s) khi thực thi command trên "
                        f"{hostname} ({timeout_hint})."
                    ),
                )
            except paramiko.SSHException as exc:
                return CommandResult(
                    status=ResultStatus.UNKNOWN_ERROR,
                    command=command,
                    duration=time.monotonic() - started,
                    error=str(exc),
                )

            duration = time.monotonic() - started

            if exit_code != 0:
                combined_lower = (out_text + err_text).lower()
                if any(marker in combined_lower for marker in _DEVICE_CONNECTION_ERROR_MARKERS):
                    return CommandResult(
                        status=ResultStatus.DEVICE_CONNECTION_FAILED,
                        command=command,
                        stdout=out_text,
                        stderr=err_text,
                        exit_code=exit_code,
                        duration=duration,
                        error=f"Không thể kết nối SSH tới thiết bị {hostname} qua NMS.",
                    )
                return CommandResult(
                    status=ResultStatus.COMMAND_FAILED,
                    command=command,
                    stdout=out_text,
                    stderr=err_text,
                    exit_code=exit_code,
                    duration=duration,
                    error=f"Command trả về mã lỗi {exit_code} trên thiết bị {hostname}.",
                )

            return CommandResult(
                status=ResultStatus.SUCCESS,
                command=command,
                stdout=out_text,
                stderr=err_text,
                exit_code=exit_code,
                duration=duration,
            )

        except Exception as exc:  # noqa: BLE001 - chặn mọi lỗi không lường trước, không để lộ traceback ra Telegram
            logger.exception("Lỗi không xác định khi chạy command trên %s", hostname)
            return CommandResult(
                status=ResultStatus.UNKNOWN_ERROR,
                command=command,
                duration=time.monotonic() - started,
                error=str(exc),
            )
        finally:
            if client is not None:
                client.close()
