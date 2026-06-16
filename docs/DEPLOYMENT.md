# Hướng dẫn triển khai từng bước (zero → chạy được)

Tài liệu này dẫn bạn đi từ con số 0 đến lúc Headscale tự host chạy thật và client kết nối được, **deploy hoàn toàn tự động qua GitHub Actions** (sửa code → push → tự lên VPS).

> Đã quen rồi? Xem nhanh [README.md](../README.md). Chi tiết riêng phần CI/CD: [CICD.md](CICD.md).

---

## Bức tranh tổng thể

```
 Máy bạn (Windows)            GitHub                         VPS (Linux)
 ┌───────────────┐  git push  ┌──────────────┐  SSH deploy   ┌──────────────────┐
 │ sửa config    │ ─────────► │ CI validate  │ ───────────►  │ docker compose up│
 │ commit        │            │ CD (ssh)     │  (tự cài+clone)│ headscale + caddy│
 └───────────────┘            └──────────────┘               └──────────────────┘
                                                                      ▲
                                                                client kết nối
```

**Checklist tổng (tick dần khi làm):**

- [ ] B1. Chuẩn bị: VPS + domain + máy local có `git`, `gh`
- [ ] B2. Tạo SSH deploy key
- [ ] B3. Đưa public key lên VPS
- [ ] B4. Khai báo 5 GitHub Secrets
- [ ] B5. Trỏ DNS domain → IP VPS
- [ ] B6. Điền domain/IP thật vào config rồi push
- [ ] B7. Xác nhận CI/CD tự deploy thành công
- [ ] B8. Tạo user + pre-auth key
- [ ] B9. Kết nối client + verify

---

## Bước 1 — Chuẩn bị

| Cần gì | Ghi chú |
|--------|---------|
| **VPS** | Ubuntu 22.04+/Debian 12+, public IP, 1 vCPU/512MB là đủ. Đăng nhập SSH được. |
| **Domain** | 1 subdomain, ví dụ `hs.example.com`. Cần quyền tạo bản ghi DNS. |
| **Mở port trên VPS** | TCP `80`, `443`; UDP `3478`. (Firewall/Security Group của nhà cung cấp) |
| **Máy local** | Cài `git` và `gh` (GitHub CLI), đã `gh auth login`. |

Kiểm tra máy local:

```powershell
git --version
gh --version
gh auth status      # phải thấy "Logged in"
```

> ⚠️ **Windows quirk của máy này**: `C:\Users\Hoanglong\.ssh` đang là *file* (không phải thư mục), nên ta để key ở thư mục riêng `C:\Users\Hoanglong\keys\`.

---

## Bước 2 — Tạo SSH deploy key

Deploy key là cặp khoá **riêng cho GitHub Actions** (đừng dùng key cá nhân). Tạo bằng Git Bash:

```bash
mkdir -p ~/keys
ssh-keygen -t ed25519 -C "github-actions-deploy-headscale" -f ~/keys/deploy_key -N ""
cat ~/keys/deploy_key.pub      # ← public key, copy chuỗi này cho Bước 3
```

Kết quả:
- `~/keys/deploy_key` → **private key** (dùng ở Bước 4, KHÔNG đưa ai)
- `~/keys/deploy_key.pub` → **public key** (dùng ở Bước 3)

---

## Bước 3 — Đưa PUBLIC key lên VPS

Mấy lệnh này chạy **TRÊN VPS**. SSH vào VPS (dấu nhắc đổi thành `user@host:~$` mới đúng), rồi:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "DÁN_PUBLIC_KEY_Ở_ĐÂY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

- `>>` = nối thêm, không xoá key cũ.
- User bạn đang đăng nhập ở đây chính là `SSH_USER` ở Bước 4.

Test deploy key từ máy local (PowerShell), thay user/IP/port cho đúng:

```powershell
ssh -i "$HOME\keys\deploy_key" -p 22 user@IP_VPS "echo OK"
```
Ra `OK` là key + quyền OK. (Nếu "connection refused" → sai **port**; xem [Bước 4](#bước-4--khai-báo-github-secrets) mục `SSH_PORT`.)

---

## Bước 4 — Khai báo GitHub Secrets

Workflow deploy đọc 5 secret này. Khai báo từ máy local bằng `gh`:

```powershell
# Private key (PowerShell không hỗ trợ '<', dùng pipe):
Get-Content "$HOME\keys\deploy_key" -Raw | gh secret set SSH_KEY --repo vanbienperu3107/deployHeadscale

gh secret set SSH_HOST    --repo vanbienperu3107/deployHeadscale --body "IP_HOAC_HOSTNAME_VPS"
gh secret set SSH_USER    --repo vanbienperu3107/deployHeadscale --body "root"            # user bạn ssh ở B3
gh secret set DEPLOY_PATH --repo vanbienperu3107/deployHeadscale --body "/opt/deployHeadscale"
gh secret set SSH_PORT    --repo vanbienperu3107/deployHeadscale --body "22"              # ĐÚNG cổng SSH của VPS
```

| Secret | Là gì | Bẫy thường gặp |
|--------|-------|----------------|
| `SSH_KEY` | toàn bộ private key (cả dòng BEGIN/END) | Dùng pipe để khỏi sai xuống dòng |
| `SSH_HOST` | IP/hostname VPS | — |
| `SSH_USER` | user SSH (vd `root`) | Phải khớp user đã thêm key ở B3 |
| `SSH_PORT` | cổng SSH | **Đặt sai = "connection refused"**. SSH thường ở 22; chỉ đổi nếu VPS dùng cổng khác |
| `DEPLOY_PATH` | thư mục repo trên VPS | Workflow tự `git clone` vào đây nếu chưa có |

Kiểm tra: `gh secret list --repo vanbienperu3107/deployHeadscale` → thấy đủ 5 dòng.

> **Không cần** tự cài Docker hay tự clone repo trên VPS — workflow deploy **tự bootstrap**: lần đầu nó tự cài `git/curl/docker` và `git clone` vào `DEPLOY_PATH`. Yêu cầu: `SSH_USER` là `root`, hoặc có `sudo` không cần mật khẩu.

---

## Bước 5 — Trỏ DNS

Tại nhà quản lý domain, tạo bản ghi **A**:

```
hs.example.com   A   <IP_VPS>
```

Đợi DNS lan (`nslookup hs.example.com` ra đúng IP). Bước này **bắt buộc trước** khi Caddy xin được chứng chỉ TLS.

---

## Bước 6 — Điền domain/IP thật rồi push

Trên **máy local**, trong repo `C:\Users\Hoanglong\deployHeadscale`, sửa placeholder:

**[config/config.yaml](../config/config.yaml):**
```yaml
server_url: https://hs.example.com          # ← domain thật
...
    ipv4: 203.0.113.10                       # ← IP public thật của VPS
...
  base_domain: tail.example.com              # ← base domain MagicDNS (khác server_url)
```

**[Caddyfile](../Caddyfile):**
```
hs.example.com {
    reverse_proxy headscale:8080
}
```

Commit + push:

```powershell
cd "$HOME\deployHeadscale"
git add -A
git commit -m "config: domain va IP that"
git push origin main
```

---

## Bước 7 — Xác nhận CI/CD tự deploy

Push xong, pipeline tự chạy. Theo dõi:

```powershell
gh run watch --repo vanbienperu3107/deployHeadscale
```

Hoặc xem trên tab **Actions**. Trình tự đúng:
1. **CI** → xanh ✅ (validate config)
2. **Deploy** tự kích hoạt → SSH vào VPS → `git reset --hard` + `docker compose up -d` → cuối log có bảng `docker compose ps` với `caddy` + `headscale` **Up**.

Kiểm tra cert + service:

```bash
curl https://hs.example.com/health        # → {"status":"ok"}
```

> Lần đầu Caddy mất ~30–60s để xin cert Let's Encrypt. Nếu lỗi cert: kiểm tra DNS (B5) và port 80/443 đã mở chưa.

---

## Bước 8 — Tạo user + pre-auth key

Chạy trên VPS (hoặc thêm vào Makefile rồi `make`):

```bash
cd /opt/deployHeadscale
docker exec headscale headscale users create myuser
docker exec headscale headscale preauthkeys create --user myuser --reusable --expiration 24h
# → in ra key dạng hskey-xxxxxxxx
```

---

## Bước 9 — Kết nối client + verify

**Linux:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --login-server=https://hs.example.com --authkey=hskey-xxxxxxxx
```

**Windows (CMD admin):**
```powershell
tailscale up --login-server=https://hs.example.com --authkey=hskey-xxxxxxxx
```

**Verify:**
```bash
docker exec headscale headscale nodes list   # trên VPS: thấy node vừa join
tailscale status                             # trên client
ping 100.64.0.1                              # ping IP tailscale node khác
```

✅ Thấy node trong danh sách + ping thông = xong.

---

## Vận hành thường ngày

Mọi thay đổi cấu hình từ giờ:

```
sửa file trong repo local → git commit → git push origin main → tự deploy
```

Không SSH vào VPS sửa tay (vì CD `git reset --hard` sẽ ghi đè). Secret thật (vd OIDC) để ở file gitignored trên VPS.

| Việc | Cách |
|------|------|
| Deploy lại không đổi code | tab Actions → Deploy → **Run workflow** |
| Xem nodes | `docker exec headscale headscale nodes list` |
| Backup DB | `docker cp headscale:/var/lib/headscale/db.sqlite ./backup/` |
| Xem log | `docker logs -f headscale` |

---

## Khắc phục sự cố (các lỗi đã thực gặp)

| Triệu chứng (trong log Deploy) | Nguyên nhân | Cách sửa |
|--------------------------------|-------------|----------|
| `dial tcp ***:***: connect: connection refused` | `SSH_PORT` sai | Đặt lại đúng cổng SSH của VPS (thường `22`) |
| `Permission denied (publickey)` | public key chưa lên VPS / `SSH_KEY` sai / sai `SSH_USER` | Làm lại B3; set lại `SSH_KEY` bằng pipe |
| `cd: ***: No such file or directory` | `DEPLOY_PATH` chưa tồn tại | Đã tự xử lý — workflow tự clone. Nếu vẫn lỗi: `SSH_USER` không có quyền tạo thư mục đó / không phải root |
| `docker: permission denied` | user chưa thuộc nhóm docker | Dùng `SSH_USER=root`, hoặc `usermod -aG docker <user>` rồi đăng nhập lại |
| Deploy không tự chạy sau CI | `ci.yml` chưa có trên `main`, hoặc CI fail | Push để CI lên main trước; xem CI fail vì sao |
| Caddy không có cert / `/health` lỗi | DNS chưa trỏ, hoặc chưa mở 80/443 | Làm B5; mở firewall |
| Headscale crash-loop | `config.yaml` còn placeholder (IP không hợp lệ) | Làm B6 (điền IP/domain thật) |
