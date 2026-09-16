# td-bot — V1

Telegram Bot kiểm tra trạng thái cổng truyền dẫn (`/checktd HOSTNAME`),
chạy trên Dell Wyse, đi qua NMS Server bằng SSH có sẵn (`~/.ssh/config.devices`)
để tới thiết bị.

## Cài đặt

```bash
cd td-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Cấu hình

```bash
cp .env.example .env
# rồi chỉnh sửa .env với giá trị thật: BOT_TOKEN, ALLOWED_GROUP_ID, NMS_HOST, NMS_USER, ...
```

Yêu cầu trước khi chạy:

- Wyse đã có SSH key để SSH được vào NMS bằng `NMS_USER` không cần mật khẩu
  (key auth, hoặc dùng ssh-agent).
- Trên NMS đã tồn tại `~/.ssh/config.devices` với Host alias khớp đúng với
  cột `hostname` trong `data/Devices.csv`.
- `data/Devices.csv` đã được điền dữ liệu thiết bị thật (V1 chỉ tạo sẵn
  header đúng cấu trúc yêu cầu, chưa có dữ liệu mẫu).
- **Nếu private key NMS dùng để SSH xuống thiết bị (trong `config.devices`)
  có passphrase: xem mục "Private key có passphrase" bên dưới — đây là điều
  kiện bắt buộc, nếu bỏ qua bot sẽ timeout ở mọi lệnh `/checktd`.**

### Private key có passphrase (NMS -> Device)

Bot chạy không tương tác (non-interactive), nên KHÔNG thể tự nhập passphrase
khi ssh ở NMS hỏi — và cũng không nên làm vậy: bot không được phép biết/lưu
passphrase hay bất kỳ thông tin xác thực thiết bị nào (đúng nguyên tắc trong
spec). Cách xử lý đúng là chuẩn bị sẵn một `ssh-agent` đã unlock private key
trên NMS, chạy độc lập với phiên của bot:

1. Cài `keychain` trên NMS (giữ ssh-agent sống qua nhiều phiên login):

   ```bash
   sudo apt install keychain   # hoặc yum/dnf tùy distro
   ```

2. Trong `~/.bash_profile` (hoặc file init của user chạy trên NMS), thêm:

   ```bash
   eval $(keychain --eval --agents ssh id_ed25519_devices)
   ```

   rồi đăng nhập lại một lần, nhập passphrase — từ đó `keychain` giữ agent
   sống, key đã unlock, cho tới khi NMS reboot hoặc agent bị kill.

3. Khai báo trong `.env` của bot (`NMS_REMOTE_ENV_SOURCE`) lệnh để nạp lại
   agent đó trong phiên SSH không tương tác mà bot mở tới NMS (phiên này
   không tự source `~/.bash_profile`):

   ```bash
   NMS_REMOTE_ENV_SOURCE=source ~/.keychain/$(hostname)-sh
   ```

4. Test thủ công trên NMS (dùng đúng user mà bot sẽ SSH vào):

   ```bash
   source ~/.keychain/$(hostname)-sh
   ssh -F ~/.ssh/config.devices <hostname-trong-Devices.csv> "show interface description"
   ```

   Nếu lệnh trên chạy được KHÔNG hỏi passphrase, cấu hình đã đúng.

Nếu bỏ qua bước này, mỗi lần `/checktd` chạy sẽ trả về lỗi
`TIMEOUT` sau đúng `SSH_TIMEOUT` giây (bot không còn bị treo vô hạn nữa nhờ
bản vá timeout, nhưng lệnh vẫn sẽ luôn thất bại cho tới khi ssh-agent được
thiết lập đúng).

### Thiết bị không có SSH key, xác thực bằng username/password

Nguyên tắc **"Bot không được biết password thiết bị"** vẫn được giữ nguyên
— bot không nhận, không lưu, không log password ở bất kỳ đâu. Thay vào đó,
password được lưu SẴN trên NMS, và bot chỉ tham chiếu đường dẫn quy ước
tới file đó.

Để đơn giản hoá triển khai: password được cấu hình **DÙNG CHUNG THEO
VENDOR** (mỗi vendor 1 password), không phải theo từng thiết bị — nhiều
thiết bị password-auth cùng vendor sẽ dùng chung 1 file password.

1. Cài `sshpass` trên NMS:

   ```bash
   sudo apt install sshpass   # hoặc yum/dnf tùy distro
   ```

2. Tạo thư mục chứa password, giới hạn quyền chỉ cho user chạy bot đọc được:

   ```bash
   mkdir -p ~/.ssh/device_secrets
   chmod 700 ~/.ssh/device_secrets
   ```

3. Với mỗi vendor có thiết bị xác thực bằng password, tạo 1 file — **tên
   file là tên vendor viết thường, khoảng trắng thay bằng `_`** (ví dụ
   `Juniper` -> `juniper`, `Cisco Systems` -> `cisco_systems`), nội dung là
   password thuần dùng chung cho cả vendor đó:

   ```bash
   echo -n 'mật khẩu dùng chung cho các thiết bị Cisco' > ~/.ssh/device_secrets/cisco
   chmod 600 ~/.ssh/device_secrets/cisco
   ```

4. Trong `Devices.csv`, đặt cột `key_type` cho các thiết bị đó thành một
   giá trị thuộc `PASSWORD_KEY_TYPES` (mặc định: `non`, `none`, hoặc
   `password`) — cột `vendor` phải đúng để bot tra đúng file password:

   ```csv
   hostname,management_ip,vendor,model,role,province,ssh_user,description,key_type
   OLD-DEVICE-01,10.0.0.5,Cisco,ASR920,PE,HN,admin,,non
   OLD-DEVICE-02,10.0.0.6,Cisco,ASR920,PE,NA,admin,,non
   ```

   Cả hai thiết bị trên đều dùng chung file `~/.ssh/device_secrets/cisco`.

5. Đảm bảo `~/.ssh/config.devices` trên NMS đã có `Host <hostname>` cho
   từng thiết bị với `User`/`HostName` đúng (Bot không tự thêm User vào
   lệnh ssh — toàn bộ thông tin kết nối khác ngoài password vẫn lấy từ
   `config.devices` như bình thường; Bot chỉ thêm `sshpass -f <file
   theo vendor>` phía trước).

6. Khai báo `DEVICE_PASSWORD_SECRETS_DIR` trong `.env` (mặc định đã trỏ tới
   `~/.ssh/device_secrets`, chỉnh nếu bạn dùng thư mục khác).

7. Test thủ công trên NMS trước khi chạy bot:

   ```bash
   sshpass -f ~/.ssh/device_secrets/cisco \
       ssh -F ~/.ssh/config.devices -o PubkeyAuthentication=no \
       OLD-DEVICE-01 "show interface description"
   ```

   Nếu chạy được không hỏi gì thêm, cấu hình đã đúng.

**Lưu ý bảo mật:** các file password này nằm ngoài `Devices.csv` và ngoài
source code của bot — không commit chúng vào git, không chia sẻ thư mục
`device_secrets` cho user khác trên NMS (đã `chmod 700`/`600` ở trên).
Vì dùng chung 1 password cho cả vendor, nếu cần thu hồi/đổi quyền truy cập
cho một thiết bị cụ thể, phải đổi password trên chính thiết bị đó và cập
nhật lại file dùng chung — ảnh hưởng tới toàn bộ thiết bị cùng vendor.

## Chạy

```bash
python run.py
```

Log được ghi vào `logs/bot.log` (và ra stdout), không ghi password/private
key/credential.

## Sử dụng trên Telegram

Trong group được cấu hình (`ALLOWED_GROUP_ID`):

```
/checktd "tên gợi ý"
```

Ví dụ: `/checktd DIEN CHAU`. Bot tìm kiếm KHÔNG phân biệt hoa/thường,
dạng chứa chuỗi con, trên cả cột `hostname` VÀ cột `alias` trong
`Devices.csv`, rồi hiển thị các thiết bị khớp dưới dạng NÚT BẤM. Bấm vào
tên thiết bị để bot thực hiện kiểm tra.

Cột `alias` (tùy chọn, thêm mới trong `Devices.csv`) cho phép gán nhiều tên
gợi nhớ cho một thiết bị, phân tách bằng dấu `;`, ví dụ:

```csv
hostname,...,alias
CSG9.1-NA_DCU_DIEN_CHAU,...,DIEN CHAU;CSG DIEN CHAU
```

Nếu Devices.csv chưa có cột `alias` (file cũ), bot vẫn chạy bình thường —
chỉ tìm kiếm được theo hostname.

**Giới hạn V1:** mỗi group chỉ giữ danh sách kết quả tìm kiếm GẦN NHẤT —
tìm kiếm mới sẽ làm các nút bấm của tìm kiếm cũ trong cùng group hết hạn.

### Vendor đã hỗ trợ

| Vendor  | Command chạy trên thiết bị        |
|---------|------------------------------------|
| Juniper | `show interface description`       |
| Cisco   | `show interfaces description`      |
| Ciena   | `show interface description`      |

Vendor khác chưa có trong `commands/registry.py` sẽ báo lỗi
`UNKNOWN_ERROR` khi `/checktd` (xem `commands/registry.py` để bổ sung).

### Định dạng kết quả

Kết quả hiển thị theo từng khối interface (không dùng bảng cố định cột) để
dễ đọc trên điện thoại:

```
Gi0/0/0 | UP/UP
└─ TO_NA_TKY_KY_SON_PO_NA_TY_NoiSite/FO/MBF
```

Parser (`parser/interface.py::parse_interface_description`) dùng chung cho
Juniper và Cisco có cấu trúc bảng 4 cột (interface, admin/status,
link/protocol, description). Ciena dùng parser riêng
`parse_ciena_interface_description` cho bảng pipe-delimited và hỗ trợ
description xuống dòng. Vendor có định dạng output khác sẽ tự động fallback
hiển thị raw output.

## Bổ sung command mới (V2+)

Theo kiến trúc phân lớp, để thêm ví dụ `/checkquang`:

1. Thêm Handler mới trong `bot/handlers/` (ví dụ `check_optical.py`).
2. Đăng ký route trong `bot/router.py`.
3. Bổ sung ánh xạ command trong `commands/registry.py`.
4. Nếu cần parser riêng, thêm module trong `parser/`.

Không cần sửa `ssh/gateway.py` hay `bot/guard.py`.

## Đã vá: lỗi "Message is too long" + chỉ hiển thị interface vật lý

Với thiết bị có nhiều interface (đặc biệt còn cộng thêm sub-interface dạng
`ge-1/2/1.102`), bảng render ra có thể vượt quá giới hạn 4096 ký tự của một
tin nhắn Telegram, gây lỗi `telegram.error.BadRequest: Message is too long`.
Đã xử lý:

- **Lọc sub-interface**: `/checktd` giờ chỉ hiển thị interface vật lý
  (bỏ các dòng có dấu `.` trong tên, ví dụ `ge-1/2/1.102`), xem
  `parser/interface.py::filter_physical_interfaces`.
- **Tự động chia trang**: nếu bảng (sau khi lọc) vẫn còn dài hơn giới hạn
  4096 ký tự, Formatter tự chia thành nhiều tin nhắn liên tiếp
  (`trang N/M`), mỗi tin nhắn đảm bảo dưới giới hạn — xem
  `formatter/telegram.py::format_checktd_success_pages`. Handler gửi lần
  lượt từng trang qua `message.reply_text`.

## Đã vá: lỗi "Can't open user config file ~/.ssh/config.devices"

Nếu log báo `Can't open user config file ~/.ssh/config.devices: No such
file or directory` dù file thực sự tồn tại và test tay `ssh -F
~/.ssh/config.devices ...` chạy được bình thường: nguyên nhân là bot dùng
`shlex.quote()` bọc đường dẫn bằng dấu nháy đơn, mà bên trong nháy đơn `~`
KHÔNG được shell giãn thành `$HOME` — ssh nhận đúng chuỗi literal
`~/.ssh/config.devices` (không tồn tại theo nghĩa đen). Đã sửa trong
`ssh/gateway.py` (`_quote_remote_path`): nếu path bắt đầu bằng `~/`, thay
bằng `$HOME/` rồi bọc nháy kép để `$HOME` vẫn được giãn đúng.

Khuyến nghị: nếu muốn chắc chắn 100%, có thể khai báo
`SSH_CONFIG_DEVICES_PATH` bằng đường dẫn tuyệt đối
(`/home/<user>/.ssh/config.devices`) thay vì dùng `~`.

## Đã vá: bot bị treo, không tắt được

Nếu bạn từng gặp bot chạy bị treo hoàn toàn và không dừng được bằng Ctrl+C,
nguyên nhân là:

1. `channel.recv_exit_status()` của paramiko chờ vô thời hạn nếu tiến trình
   phía NMS không bao giờ thoát — đã thay bằng vòng poll có deadline
   (`SSH_TIMEOUT`) trong `ssh/gateway.py`.
2. Lệnh SSH (blocking) trước đây chạy trực tiếp trên event loop bất đồng bộ
   của Telegram, nên khi bị treo ở (1), toàn bộ bot đứng hình theo — đã sửa
   để chạy trong thread riêng (`asyncio.to_thread`) trong
   `bot/handlers/checktd.py`.
3. Nguyên nhân khiến ssh ở NMS treo trong trường hợp của bạn: private key
   dùng để NMS SSH xuống thiết bị có passphrase, mà lệnh chạy không có pty
   nên ssh chờ đọc passphrase từ một stdin không bao giờ có dữ liệu — đã
   thêm `< /dev/null` để ssh nhận EOF ngay và thoát bằng lỗi thay vì treo,
   và cần thiết lập ssh-agent trên NMS (xem mục trên) để lệnh thật sự chạy
   được thay vì luôn timeout.

## Giới hạn phạm vi V1

Không bao gồm: database, Web UI/Streamlit/Dashboard, user management phức
tạp, arbitrary CLI, quản lý SSH key, thay đổi cấu hình thiết bị.
