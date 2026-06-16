# Hướng dẫn CI/CD cho deployHeadscale qua GitHub Actions

Tài liệu này giải thích cách thiết lập CI/CD: mỗi khi bạn `git push` lên nhánh `main`, GitHub sẽ tự **kiểm tra cấu hình** rồi **SSH vào VPS deploy** Headscale.

```
 git push main
      │
      ▼
┌──────────────┐   pass   ┌──────────────────┐   SSH    ┌──────────────┐
│  CI workflow │ ───────► │  Deploy workflow │ ───────► │     VPS      │
│  (validate)  │          │  (ssh-action)    │          │ git pull +   │
└──────────────┘          └──────────────────┘          │ compose up   │
                                                          └──────────────┘
```

- **CI** (`.github/workflows/ci.yml`): validate `docker-compose.yml`, `config.yaml`, `acl.json`, `Caddyfile`, quét private key bị commit nhầm. Chạy trên **mọi** push & pull request.
- **CD** (`.github/workflows/deploy.yml`): chạy **sau khi CI pass** trên `main`, SSH vào VPS chạy `git reset --hard origin/main` + `docker compose pull` + `docker compose up -d`.

---

## Mô hình bí mật (đọc trước khi làm)

| Giá trị | Bí mật? | Để ở đâu |
|---------|---------|----------|
| Domain (`hs.yourdomain.com`), public IP | ❌ Không (DNS/IP vốn công khai) | Commit thẳng vào repo |
| SSH key deploy, host, user | ✅ Có | **GitHub Secrets** |
| OIDC client secret, token... | ✅ Có | **File trên VPS** (gitignored), tham chiếu qua `*_path` trong config |
| noise/derp private key, db.sqlite | ✅ Có | Tự sinh trong Docker volume, **không** vào repo (đã `.gitignore`) |

> CD dùng `git reset --hard origin/main`, nên **đừng sửa file đã được track trực tiếp trên VPS** — sẽ bị ghi đè. Mọi thay đổi cấu hình hãy commit qua Git. Các secret thật để ở file gitignored (`.env`, file secret) — `reset --hard` không đụng tới file gitignored.

---

## Phần 1 — Chuẩn bị VPS (làm 1 lần)

### 1.1 Cài Docker + clone repo

```bash
# Cài Docker (nếu chưa có)
curl -fsSL https://get.docker.com | sh

# Clone repo về VPS (đặt ở đâu cũng được, nhớ đường dẫn này)
sudo git clone https://github.com/vanbienperu3107/deployHeadscale.git /opt/deployHeadscale
cd /opt/deployHeadscale
```

### 1.2 Điền giá trị thật rồi commit

Sửa placeholder trong `config/config.yaml` và `Caddyfile` (`hs.yourdomain.com`, `tail.yourdomain.com`, `YOUR_SERVER_PUBLIC_IP`).
Cách sạch nhất: **sửa trên máy bạn → commit → push**, rồi trên VPS `git pull`. Như vậy working tree trên VPS luôn khớp `origin/main` để CD không bị xung đột.

### 1.3 Deploy tay lần đầu (để chắc chắn chạy được)

```bash
cd /opt/deployHeadscale
docker compose up -d
sleep 30
curl -fsS https://hs.yourdomain.com/health   # → {"status":"ok"}
```

Nếu lần này OK thì CD tự động về sau cũng OK.

---

## Phần 2 — Tạo SSH key riêng cho deploy

**Đừng** dùng key cá nhân của bạn. Tạo key riêng cho GitHub Actions để dễ thu hồi.

Trên máy local (hoặc ngay trên VPS):

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/deploy_key -N ""
```

Sinh ra 2 file:
- `~/deploy_key` — **private key** → nạp vào GitHub Secrets (`SSH_KEY`)
- `~/deploy_key.pub` — **public key** → cho vào VPS

Thêm public key vào VPS (cho user mà Actions sẽ SSH vào):

```bash
# Chạy trên VPS, dán nội dung deploy_key.pub vào
cat >> ~/.ssh/authorized_keys < deploy_key.pub
chmod 600 ~/.ssh/authorized_keys
```

> **An toàn hơn (khuyến nghị):** tạo user riêng `deploy` có quyền chạy docker, chỉ dùng cho CD:
> ```bash
> sudo adduser --disabled-password --gecos "" deploy
> sudo usermod -aG docker deploy
> sudo mkdir -p /home/deploy/.ssh && sudo nano /home/deploy/.ssh/authorized_keys  # dán public key
> sudo chown -R deploy:deploy /home/deploy/.ssh && sudo chmod 700 /home/deploy/.ssh
> sudo chmod 600 /home/deploy/.ssh/authorized_keys
> # đảm bảo /opt/deployHeadscale do user deploy sở hữu
> sudo chown -R deploy:deploy /opt/deployHeadscale
> ```

---

## Phần 3 — Khai báo GitHub Secrets

Vào repo trên GitHub → **Settings → Secrets and variables → Actions → New repository secret**, thêm:

| Secret | Giá trị | Ví dụ |
|--------|---------|-------|
| `SSH_HOST` | IP hoặc hostname VPS | `203.0.113.10` |
| `SSH_USER` | user để SSH | `deploy` (hoặc `root`) |
| `SSH_KEY` | **toàn bộ** nội dung file private key `~/deploy_key` | `-----BEGIN OPENSSH PRIVATE KEY-----\n...` |
| `DEPLOY_PATH` | thư mục repo trên VPS | `/opt/deployHeadscale` |
| `SSH_PORT` | *(tùy chọn)* cổng SSH nếu khác 22 | `2222` |

Hoặc dùng `gh` CLI từ máy có quyền (nhanh hơn):

```bash
gh secret set SSH_HOST    --repo vanbienperu3107/deployHeadscale --body "203.0.113.10"
gh secret set SSH_USER    --repo vanbienperu3107/deployHeadscale --body "deploy"
gh secret set DEPLOY_PATH --repo vanbienperu3107/deployHeadscale --body "/opt/deployHeadscale"
gh secret set SSH_KEY     --repo vanbienperu3107/deployHeadscale < ~/deploy_key
# gh secret set SSH_PORT  --repo vanbienperu3107/deployHeadscale --body "2222"   # nếu cần
```

> Lưu ý với `SSH_KEY`: phải là **private key đầy đủ** kể cả dòng `-----BEGIN/END-----`. Dùng `gh secret set SSH_KEY < file` để khỏi sai định dạng xuống dòng.

---

## Phần 4 — Chạy thử

```bash
# Sửa gì đó (ví dụ README) rồi:
git add -A && git commit -m "test ci/cd" && git push origin main
```

Vào tab **Actions** trên GitHub xem:
1. **CI** chạy trước → xanh ✅
2. **Deploy** tự kích hoạt → SSH vào VPS → `docker compose ps` ở cuối log.

Muốn deploy lại mà không cần đổi code: tab **Actions → Deploy → Run workflow** (nút bấm tay).

---

## Cách hoạt động (chi tiết kỹ thuật)

- **Gate "CI pass mới deploy"**: `deploy.yml` dùng trigger `workflow_run` lắng nghe workflow `CI`, kèm điều kiện `if: github.event.workflow_run.conclusion == 'success'`. Nếu CI fail thì Deploy không chạy.
- **`concurrency: deploy-production`**: hai lần push sát nhau không deploy đè lên nhau.
- **`git reset --hard origin/main`**: đảm bảo VPS đúng y hệt nhánh main, tránh xung đột do drift. File gitignored (`.env`, secret, volume data) không bị ảnh hưởng.
- **`appleboy/ssh-action`**: action SSH phổ biến. Có thể nâng version mới hơn — kiểm tra tại https://github.com/appleboy/ssh-action/releases.

---

## Biến thể: giữ domain/IP riêng tư (Option B)

Nếu **không muốn** commit domain/IP thật vào repo public, dùng template + `.env`:

1. Đổi tên `config/config.yaml` → `config/config.yaml.tmpl`, `Caddyfile` → `Caddyfile.tmpl`, thay giá trị thật bằng `${HS_DOMAIN}`, `${HS_BASE_DOMAIN}`, `${HS_PUBLIC_IP}`.
2. Thêm `config/config.yaml` và `Caddyfile` vào `.gitignore` (file render ra, không commit).
3. Trên VPS tạo `.env` (gitignored) chứa giá trị thật.
4. Thêm bước render vào script deploy (`deploy.yml`), **trước** `docker compose up`:
   ```bash
   set -a && . ./.env && set +a
   envsubst < config/config.yaml.tmpl > config/config.yaml
   envsubst < Caddyfile.tmpl > Caddyfile
   ```

Khi đó repo public chỉ chứa template, giá trị thật nằm trong `.env` trên VPS.

---

## Khắc phục sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|-------------|--------------------------|
| Deploy job báo `Permission denied (publickey)` | Public key chưa nằm trong `authorized_keys` đúng user, hoặc `SSH_KEY` sai. Kiểm tra `SSH_USER`/`SSH_KEY`. |
| `Host key verification failed` | `appleboy/ssh-action` tự bỏ qua, nếu vẫn lỗi thêm `fingerprint`/`use_insecure_cipher` (xem README action). |
| `git reset` báo lỗi | Thư mục `DEPLOY_PATH` không phải git repo hoặc user không có quyền. Kiểm tra quyền sở hữu. |
| `docker: permission denied` | User deploy chưa thuộc nhóm `docker`: `sudo usermod -aG docker <user>` rồi đăng nhập lại. |
| Deploy không tự chạy sau CI | Trigger `workflow_run` chỉ chạy khi `ci.yml` đã có trên `main`. Lần đầu phải push CI lên main trước. |
| CI fail ở bước Caddyfile | Sai cú pháp Caddyfile — chạy `caddy validate` local để xem chi tiết. |

---

## Bảo mật

- Dùng SSH key **riêng cho deploy**, có thể thu hồi bằng cách xóa dòng trong `authorized_keys`.
- Hạn chế quyền: user `deploy` chỉ cần chạy docker, không cần `sudo` toàn quyền.
- Có thể giới hạn key chỉ chạy đúng lệnh deploy bằng `command="..."` trong `authorized_keys`.
- Cân nhắc bật **GitHub Environment** `production` có "Required reviewers" nếu muốn duyệt tay trước khi deploy (đổi `deploy.yml`: thêm `environment: production` vào job).
