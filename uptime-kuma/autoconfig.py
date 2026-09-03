"""Tu dong cau hinh Uptime Kuma qua API (socket.io) — chay tren GitHub runner.

Idempotent: chay lai bao nhieu lan cung duoc.
  - Chua co admin -> setup admin (KUMA_USER/KUMA_PASS).
  - Notification Telegram (default, apply toan bo) — tao neu chua co.
  - Cac monitor check chu dong + 2 Push monitor (docker-vpn4/docker-vpn6),
    tao theo TEN, da ton tai thi giu nguyen.
  - In push token ra GITHUB_OUTPUT (da add-mask) de buoc sau cai heartbeat.

Env: KUMA_URL, KUMA_USER, KUMA_PASS, TG_TOKEN, TG_CHAT
Thu vien: uptime-kuma-api (pin trong workflow, tuong thich Kuma 1.23.x).
"""
import os
import sys

from uptime_kuma_api import UptimeKumaApi, MonitorType

URL = os.environ["KUMA_URL"]
USER = os.environ["KUMA_USER"]
PASS = os.environ["KUMA_PASS"]
TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT = os.environ["TG_CHAT"]

# wait_events cao hon binh thuong: duong den Kuma di qua sslh + Caddy,
# socket.io co the roi ve long-polling nen event ve cham.
api = UptimeKumaApi(URL, timeout=90, wait_events=3.0)
print("Da ket noi socket.io")

# KHONG goi api.info(): tren duong proxy nay event INFO hay bi nuot -> Timeout
# (kiem chung run 33782246954); info chi de in version, bo duoc.

if api.need_setup():
    print("Chua co admin -> setup")
    api.setup(USER, PASS)
api.login(USER, PASS)
print("Login OK")

# --- Notification Telegram (default + apply cho monitor da co) ---
NOTIF_NAME = "Telegram VotamAIbot"
notifs = api.get_notifications()
notif = next((n for n in notifs if n["name"] == NOTIF_NAME), None)
if notif is None:
    notif = api.add_notification(
        name=NOTIF_NAME,
        type="telegram",
        isDefault=True,
        applyExisting=True,
        telegramBotToken=TG_TOKEN,
        telegramChatID=TG_CHAT,
    )
    print("Da tao notification Telegram")
else:
    print("Notification Telegram da co")
notif_id = notif["id"]

# --- Monitors (idempotent theo ten) ---
existing = {m["name"]: m for m in api.get_monitors()}


def ensure(name, **kwargs):
    if name in existing:
        print(f"Monitor '{name}' da co (id={existing[name]['id']})")
        return existing[name]
    r = api.add_monitor(name=name, notificationIDList=[notif_id], **kwargs)
    print(f"Da tao monitor '{name}'")
    return r


# 426 Upgrade Required = derper song; chap nhan ca dai 4xx cho endpoint DERP.
OK_2XX_4XX = ["200-299", "300-399", "400-499"]

ensure("DERP vpn6", type=MonitorType.HTTP,
       url="https://vpn6.hangocthanh.io.vn/derp",
       accepted_statuscodes=OK_2XX_4XX, interval=60)
ensure("DERP vpn4 (TCP 443)", type=MonitorType.PORT,
       hostname="149.104.66.174", port=443, interval=60)
ensure("Headscale", type=MonitorType.HTTP,
       url="https://vpn2.hangocthanh.io.vn/health", interval=60)
ensure("Dashboard", type=MonitorType.HTTP,
       url="https://dashboard.hangocthanh.io.vn", interval=60)
ensure("CLIProxy", type=MonitorType.HTTP,
       url="https://cliproxy.hangocthanh.io.vn",
       accepted_statuscodes=OK_2XX_4XX, interval=60)
ensure("OpenCode", type=MonitorType.HTTP,
       url="https://opencode.hangocthanh.io.vn",
       accepted_statuscodes=OK_2XX_4XX, interval=60)

# Push: interval = chu ky heartbeat ky vong; cron push moi 60s -> dat 120s
# de 1 lan cron truot mang khong bao gia.
ensure("docker-vpn4", type=MonitorType.PUSH, interval=120)
ensure("docker-vpn6", type=MonitorType.PUSH, interval=120)

# --- Lay push token, ghi GITHUB_OUTPUT (masked) ---
monitors = {m["name"]: m for m in api.get_monitors()}
out = os.environ.get("GITHUB_OUTPUT")
for name, key in (("docker-vpn4", "push_vpn4"), ("docker-vpn6", "push_vpn6")):
    tok = monitors[name].get("pushToken", "")
    if not tok:
        print(f"LOI: khong lay duoc pushToken cua {name}", file=sys.stderr)
        sys.exit(1)
    print(f"::add-mask::{tok}")
    if out:
        with open(out, "a") as f:
            f.write(f"{key}={tok}\n")

api.disconnect()
print("Autoconfig XONG")
