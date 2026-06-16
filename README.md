# deployHeadscale

[![CI](https://github.com/vanbienperu3107/deployHeadscale/actions/workflows/ci.yml/badge.svg)](https://github.com/vanbienperu3107/deployHeadscale/actions/workflows/ci.yml)
[![Deploy](https://github.com/vanbienperu3107/deployHeadscale/actions/workflows/deploy.yml/badge.svg)](https://github.com/vanbienperu3107/deployHeadscale/actions/workflows/deploy.yml)

Bộ cấu hình **deploy Headscale** (control plane self-host cho Tailscale) bằng Docker Compose + Caddy (auto TLS) + DERP embedded.

Thay thế hoàn toàn `controlplane.tailscale.com` và DERP servers của Tailscale Inc bằng server riêng của bạn.

```
┌──────────────────────────────────────────────────────────┐
│                       VPS / Server                         │
│  ┌──────────┐ ┌──────────┐ ┌───────────────┐ ┌─────────┐  │
│  │ Headscale│ │DERP embed│ │headscale-admin│ │oauth2-  │  │
│  │ :8080    │ │ :3478/udp│ │  (Web UI)     │ │proxy SSO│  │
│  └────┬─────┘ └────┬─────┘ └───────┬───────┘ └────┬────┘  │
│   ┌───┴────────────┴───────────────┴──────────────┴───┐   │
│   │              Caddy (auto TLS :443)                 │   │
│   │   /  → headscale   /admin → SSO → admin UI         │   │
│   └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
        ▲                  ▲
   HTTPS│            DERP  │
   ┌────┴────┐        ┌────┴────┐
   │ Client A│◄──────►│ Client B│
   └─────────┘ direct └─────────┘
```

> 🟢 **Đang chạy thật:** `https://vpn2.hangocthanh.io.vn` — control plane + Web UI `/admin` (SSO Google) + DERP self-host, auto-deploy qua GitHub Actions.

---

> 📘 **Mới bắt đầu?** Theo [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — hướng dẫn triển khai **từng bước từ số 0 → chạy được** (VPS, SSH key, Secrets, DNS, CI/CD tự deploy).

## Yêu cầu

| Thành phần | Tối thiểu |
|------------|-----------|
| VPS | 1 vCPU, 512MB RAM, public IP |
| OS | Ubuntu 22.04+ / Debian 12+, Docker + Docker Compose |
| Domain | 1 subdomain trỏ về IP VPS (ví dụ `hs.yourdomain.com`) |
| Ports mở | TCP 80, 443 — UDP 3478 |

---

## Cấu trúc repo

```
deployHeadscale/
├── docker-compose.yml      # Headscale + headscale-admin + oauth2-proxy + Caddy
├── Caddyfile               # reverse proxy + auto TLS + SSO gate cho /admin
├── .env.example            # biến OIDC mẫu (secret thật ghi vào .env trên VPS)
├── config/
│   ├── config.yaml         # config chính của Headscale
│   └── acl.json            # ACL policy (mặc định: allow all)
├── oauth2-proxy/
│   └── emails.txt          # whitelist email được phép vào /admin
├── .github/workflows/
│   ├── ci.yml              # validate config trên mọi push/PR
│   └── deploy.yml          # SSH tự deploy lên VPS sau khi CI pass
├── docs/                   # DEPLOYMENT.md (zero→chạy), CICD.md
└── Makefile                # lệnh tắt tiện dụng
```

---

## Quick start

### 1. Clone & cấu hình

```bash
git clone https://github.com/vanbienperu3107/deployHeadscale.git
cd deployHeadscale
cp .env.example .env
```

Sửa các giá trị placeholder (xem bảng bên dưới) trong:
- `config/config.yaml` — `hs.yourdomain.com`, `tail.yourdomain.com`, `YOUR_SERVER_PUBLIC_IP`
- `Caddyfile` — `hs.yourdomain.com`

| Placeholder | Ý nghĩa | Ví dụ |
|-------------|---------|-------|
| `hs.yourdomain.com` | domain control plane | `hs.example.com` |
| `tail.yourdomain.com` | base domain cho MagicDNS | `tail.example.com` |
| `YOUR_SERVER_PUBLIC_IP` | IPv4 public của VPS | `203.0.113.10` |

### 2. Khởi động

```bash
make up        # hoặc: docker compose up -d
# Chờ ~30s cho Caddy lấy cert
make health    # curl https://hs.yourdomain.com/health
```

### 3. Tạo user + pre-auth key

```bash
make user NAME=myuser
make authkey NAME=myuser           # in ra hskey-xxxxxxxx
```

### 4. Kết nối client

**Linux**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up \
  --login-server=https://hs.yourdomain.com \
  --authkey=hskey-xxxxxxxx
```

**Windows (CMD admin)**
```powershell
tailscale up --login-server=https://hs.yourdomain.com --authkey=hskey-xxxxxxxx
```

**macOS** — đổi *Control server URL* sang `https://hs.yourdomain.com` rồi đăng nhập.

**Android (app Play Store mới)** — bản app Tailscale gần đây **bỏ ô nhập custom server**, nên không gõ login-server được. Dùng cách web-auth:
```bash
# Trên điện thoại: chạy "tailscale up" → app hiện link đăng ký (mã key)
# Trên VPS, lấy key đó đăng ký vào user của bạn:
docker exec headscale headscale nodes register --user myuser --key <KEY_TỪ_ĐIỆN_THOẠI>
```
(Điện thoại không gửi hostname nên node có thể tên `invalid-xxxx` — đổi lại bằng `headscale nodes rename -i <ID> ten-moi`.)

### 5. Verify

```bash
make nodes                 # danh sách nodes trên server
tailscale status           # trên client
ping 100.64.0.2            # test connectivity
```

---

## CI/CD (tự động deploy)

Repo có sẵn 2 GitHub Actions workflow:

- **CI** ([ci.yml](.github/workflows/ci.yml)) — validate `docker-compose.yml`, `config.yaml`, `acl.json`, `Caddyfile` trên mọi push/PR.
- **Deploy** ([deploy.yml](.github/workflows/deploy.yml)) — sau khi CI pass trên `main`, tự SSH vào VPS chạy `git reset --hard` + `docker compose up -d`.

Cần khai báo Secrets: `SSH_HOST`, `SSH_USER`, `SSH_KEY`, `DEPLOY_PATH` (và `SSH_PORT` nếu khác 22), cùng 3 secret SSO `OAUTH2_PROXY_CLIENT_ID` / `_CLIENT_SECRET` / `_COOKIE_SECRET` (xem [Web UI + SSO](#web-ui--sso-admin)).

👉 Hướng dẫn đầy đủ: [docs/CICD.md](docs/CICD.md)

---

## Web UI + SSO (`/admin`)

Stack kèm sẵn giao diện quản lý web giống admin console của Tailscale, đặt tại `https://hs.yourdomain.com/admin`, được **bảo vệ bằng đăng nhập Google (OIDC)**.

```
trình duyệt → /admin → Caddy forward_auth → oauth2-proxy → Google login
                                   │ (email nằm trong whitelist?)
                                   ▼ đạt
                            headscale-admin (Web UI)
```

| Thành phần | Image | Vai trò |
|------------|-------|---------|
| `headscale-admin` | `goodieshq/headscale-admin:v0.27` | Web UI quản lý user/node/route |
| `oauth2-proxy` | `quay.io/oauth2-proxy/oauth2-proxy:v7.6.0` | Gác cổng SSO Google trước `/admin` |

**Cấu hình cần có:**
1. **OAuth client (Google Cloud Console)** → Authorized redirect URI = `https://hs.yourdomain.com/oauth2/callback`.
2. **3 Secrets** (workflow Deploy tự ghi vào `.env` trên VPS): `OAUTH2_PROXY_CLIENT_ID`, `OAUTH2_PROXY_CLIENT_SECRET`, `OAUTH2_PROXY_COOKIE_SECRET` (`openssl rand -base64 32`).
3. **Whitelist email** trong [`oauth2-proxy/emails.txt`](oauth2-proxy/emails.txt) — mỗi dòng 1 email được phép vào.

**Đăng nhập vào UI lần đầu:** tạo API key trên VPS rồi nhập vào ô Settings của UI:
```bash
docker exec headscale headscale apikeys create --expiration 90d
# → dán key + URL https://hs.yourdomain.com vào màn hình Settings của headscale-admin
```

> ⚠️ **Phải khớp version** `headscale` ↔ `headscale-admin`. Headscale `0.28` đổi định dạng API key (`hskey-api-...`) khiến admin cũ báo *Not Authorized*; stack này ghim cặp ổn định **headscale `0.27.1` + admin `v0.27`**. Đổi version thì đổi cả hai.

---

## Bảo trì

| Task | Lệnh |
|------|------|
| Xem nodes | `make nodes` |
| Xóa node | `docker exec headscale headscale nodes delete -i <ID>` |
| Tạo user | `make user NAME=<name>` |
| Pre-auth key | `make authkey NAME=<name>` |
| Xem routes | `docker exec headscale headscale routes list` |
| Backup DB | `make backup` |
| Update | đổi image tag trong `docker-compose.yml` → `make pull && make up` |
| Logs | `make logs` |

---

## Hardening (sau khi chạy ổn)

1. **Siết ACL** — thay `"src": ["*"]` trong `config/acl.json` bằng user/group cụ thể.
2. **OIDC cho node** — `/admin` đã có SSO Google (oauth2-proxy). Muốn bắt cả *đăng nhập node* qua OIDC thì bật thêm trong `config/config.yaml`.
3. **Firewall** — chỉ mở TCP 80/443, UDP 3478. Đóng 8080/9090/50443 khỏi public.
4. **Backup tự động** — cron job `make backup`.
5. **Monitoring** — Prometheus scrape `:9090/metrics`.

---

## Kết hợp với Proxy Patch

Khi client chạy sau corporate proxy, kết hợp với `proxy.conf` patch (custom Tailscale build):

```json
{
  "enabled": true,
  "httpProxy": "http://your-corporate-proxy:8080",
  "httpsProxy": "http://your-corporate-proxy:8080"
}
```

Flow: control plane + DERP relay đi qua HTTP proxy → Headscale self-hosted; logs tắt (`logtail.enabled: false`); P2P trực tiếp qua UDP, fallback DERP nếu bị block.
