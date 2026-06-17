# Hướng dẫn chuyển sang server mới (CI/CD tự động)

Chuyển toàn bộ stack Headscale sang **VPS mới `165.22.12.169`**, vẫn deploy tự động qua GitHub Actions (push → CI → SSH deploy).

> Hướng dẫn này **giữ nguyên domain** `vpn2.hangocthanh.io.vn`, chỉ đổi IP. Muốn đổi luôn domain → xem [Phụ lục A](#phụ-lục-a--nếu-đổi-sang-domain-mới). Muốn giữ các thiết bị đã đăng ký (không phải join lại) → xem [Phụ lục B](#phụ-lục-b--giữ-thiết-bị-đã-đăng-ký-migrate-data).

Vì workflow Deploy **tự bootstrap** (tự cài git/docker + clone repo), trên VPS mới bạn gần như chỉ cần: mở port + nạp SSH key + đổi vài giá trị → push.

---

## Checklist tổng

- [ ] B1. Chuẩn bị VPS mới `165.22.12.169` (mở port, SSH vào được)
- [ ] B2. Nạp deploy public key vào VPS mới
- [ ] B3. Đổi GitHub Secret `SSH_HOST` → `165.22.12.169`
- [ ] B4. Sửa `config/config.yaml`: DERP `ipv4` → `165.22.12.169`
- [ ] B5. Trỏ DNS `vpn2.hangocthanh.io.vn` → `165.22.12.169`
- [ ] B6. Commit + push → CI/CD tự deploy
- [ ] B7. Kiểm tra service lên (`/health`, cert, API)
- [ ] B8. Đưa thiết bị vào lại (hoặc Phụ lục B nếu giữ data)
- [ ] B9. Dọn server cũ `138.68.58.101`

---

## Bước 1 — Chuẩn bị VPS mới `165.22.12.169`

| Cần | Ghi chú |
|-----|---------|
| SSH vào được | user `root` (hoặc user có `sudo` không cần mật khẩu) |
| Mở port | **TCP 80, 443** (Caddy/TLS), **UDP 3478** (DERP/STUN), và cổng **SSH** (22) |
| Docker | **Không cần cài tay** — workflow tự cài lần đầu |

> ⚠️ **Quan trọng (lỗi đã gặp ở server cũ):** nếu nhà cung cấp có **Cloud Firewall** (DigitalOcean) thì phải mở các cổng trên ở đó nữa. Cổng SSH **bị chặn/DROP** sẽ làm deploy lỗi `dial tcp i/o timeout`. GitHub runner dùng **IP động** nên cổng SSH phải mở cho mọi IP (hoặc whitelist dải IP GitHub Actions).

Kiểm tra port sau khi mở (từ máy local):

```powershell
Test-NetConnection 165.22.12.169 -Port 22
```

---

## Bước 2 — Nạp deploy public key vào VPS mới

Dùng lại đúng deploy key cũ (`C:\Users\Hoanglong\keys\deploy_key`) → khỏi đổi secret `SSH_KEY`.

Xem public key trên máy local:

```powershell
Get-Content "$HOME\keys\deploy_key.pub"
```

SSH vào VPS mới rồi dán chuỗi đó vào `authorized_keys`:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "DÁN_PUBLIC_KEY_Ở_ĐÂY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Test deploy key từ local (phải ra `OK`):

```powershell
ssh -i "$HOME\keys\deploy_key" root@165.22.12.169 "echo OK"
```

- `connection refused` → sai cổng SSH (đặt lại `SSH_PORT` ở B3).
- `i/o timeout` → firewall chặn cổng SSH (mở lại ở Bước 1).
- `Permission denied` → public key chưa vào đúng `authorized_keys` / sai user.

---

## Bước 3 — Đổi GitHub Secret `SSH_HOST`

Chỉ cần đổi **IP**. Các secret khác (`SSH_USER`, `SSH_KEY`, `SSH_PORT`, `DEPLOY_PATH`, `OAUTH2_PROXY_*`) **giữ nguyên** nếu user/cổng SSH không đổi.

```powershell
gh secret set SSH_HOST --repo vanbienperu3107/deployHeadscale --body "165.22.12.169"
```

Nếu VPS mới dùng cổng SSH khác 22, đổi thêm:

```powershell
gh secret set SSH_PORT --repo vanbienperu3107/deployHeadscale --body "CỔNG_SSH_MỚI"
```

Kiểm tra: `gh secret list --repo vanbienperu3107/deployHeadscale` → vẫn đủ 8 secret.

---

## Bước 4 — Sửa config trỏ IP mới

Chỉ **1 chỗ bắt buộc** (vì giữ domain): IP của DERP trong [`config/config.yaml`](../config/config.yaml).

```yaml
# config/config.yaml  (mục derp.server)
    ipv4: 165.22.12.169    # ← đổi từ 138.68.58.101 sang IP server mới
```

> DERP embedded quảng bá IP này cho client làm relay. Quên đổi → relay trỏ về server cũ, P2P fallback hỏng. `server_url`, `base_domain`, `Caddyfile`, `docker-compose.yml` **không đổi** vì giữ nguyên domain.

---

## Bước 5 — Trỏ DNS sang IP mới

Tại nhà quản lý domain, sửa bản ghi **A**:

```
vpn2.hangocthanh.io.vn   A   165.22.12.169
```

- Đợi DNS lan rồi kiểm tra: `nslookup vpn2.hangocthanh.io.vn` → phải ra `165.22.12.169`.
- `tail.hangocthanh.io.vn` (base_domain) **không cần** bản ghi A — nó chỉ dùng nội bộ cho MagicDNS.
- Hạ TTL trước vài giờ nếu muốn DNS đổi nhanh.

---

## Bước 6 — Commit + push → tự deploy

```powershell
cd "$HOME\deployHeadscale"
git add config/config.yaml
git commit -m "migrate: chuyen sang server moi 165.22.12.169"
git push origin main
```

Theo dõi pipeline:

```powershell
gh run watch --repo vanbienperu3107/deployHeadscale
```

Trình tự đúng: **CI** xanh ✅ → **Deploy** tự chạy (trigger `workflow_run`) → SSH vào `165.22.12.169` → tự cài docker + clone repo + `docker compose up -d --force-recreate`.

Nếu Deploy không tự kích hoạt, chạy tay:

```powershell
gh workflow run deploy.yml --repo vanbienperu3107/deployHeadscale
```

---

## Bước 7 — Kiểm tra service trên server mới

```bash
# Cert + control plane (đợi Caddy ~30–60s để xin cert Let's Encrypt cho IP mới)
curl -fsS https://vpn2.hangocthanh.io.vn/health        # → {"status":"pass"}

# API còn sống? (thay <APIKEY> bằng key thật)
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer <APIKEY>" https://vpn2.hangocthanh.io.vn/api/v1/node   # → 200
```

- Web UI: mở `https://vpn2.hangocthanh.io.vn/admin` → đăng nhập Google → vào Nodes (ô **URL** trong Settings = `https://vpn2.hangocthanh.io.vn`, **không** kèm `/admin`).
- Lỗi cert → DNS chưa trỏ IP mới hoặc 80/443 chưa mở.

---

## Bước 8 — Đưa thiết bị vào lại

> Bỏ qua bước này nếu bạn làm theo [Phụ lục B](#phụ-lục-b--giữ-thiết-bị-đã-đăng-ký-migrate-data) (giữ data — thiết bị tự nối lại).

Server mới khởi tạo **DB trống**, nên cần tạo user + cho thiết bị join lại:

```bash
# Trên VPS mới
docker exec headscale headscale users create votam
docker exec headscale headscale preauthkeys create --user votam --reusable --expiration 24h
# → hskey-xxxx
```

Trên từng máy (dùng `--reset` để ghi đè cấu hình cũ trỏ server cũ):

```powershell
tailscale up --reset --login-server=https://vpn2.hangocthanh.io.vn --authkey=hskey-xxxx
```

Android (app mới bỏ ô custom server) → web-auth:

```bash
docker exec headscale headscale nodes register --user votam --key <KEY_TỪ_ĐIỆN_THOẠI>
```

---

## Bước 9 — Dọn server cũ `138.68.58.101`

Chỉ làm **sau khi** server mới chạy ổn và thiết bị đã nối lại:

```bash
# Trên server cũ (nếu còn vào được)
cd /opt/deployHeadscale && docker compose down
```

Rồi huỷ Droplet cũ + xoá bản ghi DNS cũ. Giữ lại bản backup DB nếu cần (xem Phụ lục B).

---

## Phụ lục A — Nếu đổi sang domain mới

Ngoài các bước trên, khi đổi domain (vd `hs.example.com`) phải sửa thêm:

| File | Sửa |
|------|-----|
| [`config/config.yaml`](../config/config.yaml) | `server_url: https://hs.example.com` |
| [`config/config.yaml`](../config/config.yaml) | `base_domain:` (đổi nếu muốn base domain MagicDNS mới — phải khác `server_url`) |
| [`Caddyfile`](../Caddyfile) | dòng nhãn site → `hs.example.com {` |
| [`docker-compose.yml`](../docker-compose.yml) | oauth2-proxy: `--redirect-url=https://hs.example.com/oauth2/callback`, `--whitelist-domain=hs.example.com`, `--cookie-domain=hs.example.com` |

Và trong **Google Cloud Console → OAuth client**: thêm **Authorized redirect URI** mới `https://hs.example.com/oauth2/callback`. `oauth2-proxy/emails.txt` giữ nguyên.

---

## Phụ lục B — Giữ thiết bị đã đăng ký (migrate data)

Sao chép dữ liệu Headscale (DB + khoá noise/derp) từ server cũ sang mới → thiết bị **không cần join lại**, danh tính server được bảo toàn.

> Yêu cầu: vẫn truy cập được **server cũ** (SSH hoặc console nhà cung cấp).

**1) Backup trên server cũ** (dừng headscale để DB nhất quán):

```bash
cd /opt/deployHeadscale
docker compose stop headscale
docker run --rm --volumes-from headscale -v "$(pwd)":/backup alpine \
  tar czf /backup/hs-data.tar.gz -C /var/lib/headscale .
docker compose start headscale     # bật lại (hoặc cứ để down nếu sắp huỷ)
```

`--volumes-from headscale` mount đúng volume dữ liệu theo đường dẫn container, khỏi cần biết tên volume.

**2) Copy file sang server mới:**

```bash
scp -i ~/keys/deploy_key /opt/deployHeadscale/hs-data.tar.gz root@165.22.12.169:/tmp/
```

**3) Restore trên server mới** — làm **sau khi đã deploy lần đầu** (B6) để volume tồn tại:

```bash
cd /opt/deployHeadscale
docker compose stop headscale
docker run --rm --volumes-from headscale -v /tmp:/backup alpine \
  sh -c "cd /var/lib/headscale && rm -rf ./* && tar xzf /backup/hs-data.tar.gz"
docker compose start headscale
```

Sau đó các thiết bị tự nối lại (vì `server_url` + khoá server không đổi, IP DERP đã cập nhật ở B4). Kiểm tra: `docker exec headscale headscale nodes list` thấy đủ node cũ.

---

## Khắc phục sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|-------------|--------------------------|
| Deploy: `dial tcp ***:*** i/o timeout` | Firewall/Cloud Firewall VPS mới **chặn cổng SSH** (gói bị DROP). Mở cổng SSH cho mọi IP; kiểm tra Cloud Firewall của nhà cung cấp |
| Deploy: `connection refused` | Sai `SSH_PORT`, hoặc sshd chưa chạy trên VPS mới |
| Deploy: `Permission denied (publickey)` | Public key chưa vào `authorized_keys` đúng user / sai `SSH_USER` |
| `/health` lỗi, không có cert | DNS chưa trỏ `165.22.12.169`, hoặc 80/443 chưa mở |
| Client nối được nhưng P2P/relay chập chờn | Quên đổi DERP `ipv4` sang `165.22.12.169` (B4) |
| Thiết bị offline sau khi chuyển | Chọn "làm mới" mà chưa join lại (B8), hoặc client còn trỏ server cũ → `tailscale up --reset ...` |
| `/admin` cứ đòi nhập key | Ô **URL** trong Settings phải là `https://vpn2.hangocthanh.io.vn` (không kèm `/admin`) |

---

> Tham chiếu: dựng từ đầu xem [DEPLOYMENT.md](DEPLOYMENT.md); chi tiết CI/CD xem [CICD.md](CICD.md).
