# vpn-gw — VPN gateway image (OpenVPN + HTTP forward-proxy)

Image một-container giữ phiên **OpenVPN** tới mạng Bitel thường trực và mở
**HTTP/HTTPS forward-proxy** (tinyproxy) cho các peer tailnet. Mục tiêu: client vào
được `https://jump.bitel.com.pe/` mà không máy nào phải tự chạy OpenVPN.

Kiến trúc tổng thể & lý do thiết kế: [docs/plan-vpn-gateway-bitel.md](../docs/plan-vpn-gateway-bitel.md).

## Thành phần trong image

| Thành phần | Vai trò |
|---|---|
| `openvpn` | Giữ `tun0` tới `181.176.242.83:6969`, nhận ~42 route nội bộ (không `redirect-gateway`) |
| `tinyproxy` | Forward-proxy CONNECT + HTTP trên `:8888`, chỉ cho `100.64.0.0/10` + localhost |
| `dnsmasq` | Split-DNS: `*.bitel.com.pe` → DNS nội bộ (`10.121.127.193/194`), còn lại → public |

Image **không** chứa tailscale. Nó chạy chung network namespace với một sidecar
tailscale chính thức (compose `network_mode: service:ts-vpngw`) để proxy nằm trên
IP `100.x` của node — client trỏ PAC `PROXY <100.x>:8888`.

## Biến môi trường

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `OVPN_CONFIG` | `/config/client.ovpn` | File .ovpn (mount vào) |
| `OVPN_AUTH` | `/config/auth.txt` | 2 dòng: username / password |
| `PROXY_PORT` | `8888` | Cổng proxy |
| `BITEL_DOMAIN` | `bitel.com.pe` | Domain đẩy qua DNS nội bộ |
| `BITEL_DNS1/2` | `10.121.127.193/194` | DNS nội bộ Bitel (đã kiểm chứng) |
| `UPSTREAM_DNS/2` | `1.1.1.1` / `8.8.8.8` | DNS public cho domain còn lại |
| `PROBE_TARGET` | `10.121.124.155:3389` | Đích probe "đường còn sống thật" — TCP tới **dịch vụ thật**, không phải link-state |
| `PROBE_TIMEOUT` | `4` | Giây cho mỗi lần probe |
| `REQUIRE_FORWARD` | `0` | `1` = healthcheck coi `ip_forward=0` là hỏng (bật khi làm subnet router) |

## Subnet route dự phòng (advertise-on-healthy)

Ngoài đường proxy, gateway có thể làm **subnet router dự phòng**: khi tailscale
trên itop (`100.64.0.21`) chết, headscale chuyển route `10.121.0.0/16` sang node
này để RDP/SMB/mọi giao thức vẫn đi được. Chi tiết + cách triển khai từng pha:
[docs/plan-vpn-route-failover.md](../docs/plan-vpn-route-failover.md).

Bốn điều **phải nhớ**, mỗi cái đều đổi bằng một sự cố thật:

1. **`sysctls: [net.ipv4.ip_forward=1]` nằm trên `ts-vpngw`, không phải `vpn-gw`.**
   `/proc/sys` trong container là read-only (đã đo). containerboot coi lỗi ghi
   sysctl là **fatal** → thoát → `restart: unless-stopped` → crashloop; mà
   `ts-vpngw` là **chủ netns** nên nó chết kéo theo tinyproxy + tun0 chết cùng.

2. **`TS_ROUTES` / `--advertise-routes` để RỖNG trong compose.** containerboot áp
   route vô điều kiện lúc khởi động, trong khi `TUN_WAIT=90` bảo đảm tun0 chưa
   lên — gateway sẽ quảng bá route khi chưa forward được gì.
   [`route-agent.sh`](route-agent.sh) trên host là **người ghi duy nhất**, và chỉ
   advertise sau khi probe TCP thành công.

3. **Probe phải là TCP tới dịch vụ thật.** `ping` vô dụng (máy đích chặn ICMP —
   fail 100% trong khi TCP 3389 bắt tay được), `ip link show tun0 up` cũng vô
   dụng (Bitel chặn theo **tài khoản**: cả dải `10.121.13.x` timeout dù có route,
   trong khi `10.121.124.x` thông).

4. **tun0 KHÔNG phủ cả `10.121.0.0/16`** — chỉ ~42 prefix rời rạc. Gói tới IP
   ngoài tập đó rơi ra `eth0` với src `100.64.x` (MASQUERADE chỉ gắn `-o tun0`)
   → rò ra internet và người dùng thấy **treo**. Luật
   `FORWARD -i tailscale0 ! -o tun0 -j REJECT` chặn thẳng để fail nhanh.
   Kill-switch sẵn có không che được ca này (nó chỉ đụng chain `OUTPUT`).

**Vùng phủ đã đo (2026-08-09):** `10.121.124.155:3389` ✅ · `10.121.13.135`
(remote DC) ❌ · `10.121.13.131` ❌ · `jump 10.121.13.186` ❌ — cả dải
`10.121.13.x` bị chặn với tài khoản OpenVPN hiện tại. Thêm IP mới vào danh sách
"đi qua VPN" thì **phải probe lại** trước khi hứa nó được bảo vệ.
| `OVPN_SKIP` | `0` | `=1` bỏ qua openvpn (test proxy) |
| `TUN_WAIT` | `60` | Số giây chờ tun0 |
| `KILLSWITCH` | `0` | `=1` chặn dải Bitel khi tun0 down |

## Chạy thử nhanh (standalone)

```bash
mkdir -p config
cp bitelhome.ovpn config/client.ovpn
printf '%s\n%s\n' 'USERNAME' 'PASSWORD' > config/auth.txt && chmod 600 config/auth.txt

docker run -d --name vpn-gw \
  --cap-add NET_ADMIN --device /dev/net/tun \
  -v "$PWD/config:/config:ro" \
  -p 127.0.0.1:8888:8888 \
  ghcr.io/vanbienperu3107/vpn-gw:latest

# Kiểm tra egress đi qua VPN (phải ra IP Bitel, không phải IP host):
docker exec vpn-gw curl -s -x http://127.0.0.1:8888 https://api.ipify.org; echo
docker exec vpn-gw curl -sI -x http://127.0.0.1:8888 https://jump.bitel.com.pe/ | head -1
```

## Image tập trung (GHCR)

Build/push bởi workflow [`.github/workflows/build-vpn-gw.yml`](../.github/workflows/build-vpn-gw.yml):
`ghcr.io/vanbienperu3107/vpn-gw:latest` và `:<sha>`. Deploy chỉ `docker pull` — không
build tại host.

## Chuyển sang server mới (migration)

Image không giữ state — toàn bộ cấu hình nằm ở `/config` (mount ngoài) và env. Để
chuyển gateway sang host khác:

1. **Cài đặt host mới**: Docker + kernel module `tun` (`/dev/net/tun`), `ip_forward=1`.
2. **Kéo image**: `docker pull ghcr.io/vanbienperu3107/vpn-gw:latest` (không cần build lại).
3. **Mang `/config`**: copy `client.ovpn` + `auth.txt` (chmod 600) sang host mới. Không
   có gì khác cần mang — không DB, không volume state.
4. **Sidecar tailscale**: cấp preauthkey mới từ headscale (`headscale preauthkeys
   create -u <id> --reusable -e 8760h`) cho node `vpn-gw` mới; hostname mới → **IP
   tailnet 100.x mới**.
5. **Cập nhật PAC**: vì PAC dựng target từ `tailnet_ip` trong DB (`vpn_gateways`),
   chỉ cần sửa `tailnet_ip` của gateway trên dashboard → PAC tự trỏ đúng IP mới.
   Không client nào phải sửa tay.
6. **Kiểm tra IP nguồn**: xác nhận VPN Bitel chấp nhận IP công cộng của host mới
   (đã xác nhận host tại `149.104.66.174`/vpn4 dùng được; host khác cần thử lại).
7. Chạy `docker compose up -d`, verify `egress = IP Bitel` như lệnh ở mục trên.
