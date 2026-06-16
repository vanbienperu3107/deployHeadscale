# deployHeadscale

Bộ cấu hình **deploy Headscale** (control plane self-host cho Tailscale) bằng Docker Compose + Caddy (auto TLS) + DERP embedded.

Thay thế hoàn toàn `controlplane.tailscale.com` và DERP servers của Tailscale Inc bằng server riêng của bạn.

```
┌──────────────────────────────────────────────┐
│                  VPS / Server                  │
│  ┌────────────┐   ┌────────────┐               │
│  │ Headscale  │   │ DERP embed │               │
│  │ :8080      │   │ :3478/udp  │               │
│  └─────┬──────┘   └─────┬──────┘               │
│   ┌────┴────────────────┴────┐                 │
│   │   Caddy (auto TLS :443)   │                 │
│   └───────────────────────────┘                │
└──────────────────────────────────────────────┘
        ▲                  ▲
   HTTPS│            DERP  │
   ┌────┴────┐        ┌────┴────┐
   │ Client A│◄──────►│ Client B│
   └─────────┘ direct └─────────┘
```

---

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
├── docker-compose.yml      # Headscale + Caddy
├── Caddyfile               # reverse proxy + auto TLS
├── .env.example            # các biến cần thay → copy thành .env
├── config/
│   ├── config.yaml         # config chính của Headscale
│   └── acl.json            # ACL policy (mặc định: allow all)
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

**macOS / Android** — đổi *Control server URL* sang `https://hs.yourdomain.com` rồi đăng nhập.

### 5. Verify

```bash
make nodes                 # danh sách nodes trên server
tailscale status           # trên client
ping 100.64.0.2            # test connectivity
```

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
2. **OIDC** — bật SSO (Google/GitHub/Authelia) trong `config/config.yaml`.
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
