#!/usr/bin/env python3
"""Sinh cliproxy/config.yaml tu template + khoa lay tu FILE DUNG CHUNG tren vpn4.

    # luc deploy (co secret trong moi truong):
    python3 render-config.py config.template.yaml config.yaml
    # chay tay tren server sau khi sua file khoa (KHONG can secret):
    python3 render-config.py config.template.yaml config.yaml --tu-config

FILE DUNG CHUNG: /opt/opencode/secrets/cliproxy.key (doi bang CLIPROXY_KEY_FILE).
Chinh file ma opencode-server mount vao container o /run/secrets/cliproxy-key.
Mot file, hai ben doc: OpenCode doc truc tiep, CLIProxy doc qua config.yaml nay.

Vi sao khong de CLIProxy doc thang file: CLIProxyAPI chi lay api-keys tu
config.yaml. Bu lai no CO watcher — ghi de config.yaml la no tu nap lai
("config successfully reloaded" trong log), khong can restart.

SU CO 2026-09-26/27 ma file nay sinh ra de chan: khoa duoc them tay qua trang
/management.html, lan deploy sau sinh lai config.yaml tu template + secret nen
xoa sach khoa do -> OpenCode 401 "Invalid API key". Gio nguon la file tren
server, deploy khong con ghi de no.

Khoa tu secret VAN duoc them vao danh sach (neu co): cac buoc verify cua deploy
chay tren runner va chi biet khoa trong secret — bo no ra la deploy do oan.
"""
import os
import pathlib
import sys

KEY_FILE_MAC_DINH = "/opt/opencode/secrets/cliproxy.key"


def doc_khoa_tu_file(duong_dan):
    """Doc khoa tu file dung chung. Moi dong mot khoa, bo dong trong va '#'."""
    try:
        tho = pathlib.Path(duong_dan).read_text(encoding="utf-8")
    except OSError:
        return []
    ra = []
    for dong in tho.splitlines():
        d = dong.strip()
        if d and not d.startswith("#"):
            ra.append(d)
    return ra


def gop_khoa(khoa_file, khoa_secret):
    """File truoc, secret sau, bo trung — giu thu tu de config on dinh giua cac lan chay."""
    ra = []
    for k in list(khoa_file) + ([khoa_secret] if khoa_secret else []):
        if k and k not in ra:
            ra.append(k)
    return ra


def khoi_api_keys(khoa):
    """Sinh khoi YAML `api-keys:`. Bao khoa trong nhay kep de ky tu la khong pha YAML."""
    dong = ["api-keys:"]
    for k in khoa:
        dong.append('  - "%s"' % k.replace("\\", "\\\\").replace('"', '\\"'))
    return "\n".join(dong)


def thay_api_keys(tho, khoa):
    """Thay ca khoi `api-keys:` (gom cac dong `-` ke tiep) bang danh sach moi."""
    dong = tho.splitlines()
    ra, i, thay_roi = [], 0, False
    while i < len(dong):
        if dong[i].startswith("api-keys:"):
            ra.append(khoi_api_keys(khoa))
            thay_roi = True
            i += 1
            while i < len(dong) and (dong[i].strip().startswith("-") or not dong[i].strip()):
                # Dung lai o dong trong NEU sau no la mot khoa khac (het khoi).
                if not dong[i].strip():
                    con_lai = [d for d in dong[i + 1:] if d.strip()]
                    if con_lai and not con_lai[0].strip().startswith("-"):
                        break
                i += 1
            continue
        ra.append(dong[i])
        i += 1
    if not thay_roi:
        raise SystemExit("template khong co khoi api-keys:")
    return "\n".join(ra) + ("\n" if tho.endswith("\n") else "")


def gia_tri_tu_config(duong_dan, ten):
    """Doc mot gia tri vo huong tu config.yaml dang co (dung khi chay tay, khong co secret)."""
    try:
        tho = pathlib.Path(duong_dan).read_text(encoding="utf-8")
    except OSError:
        return ""
    for dong in tho.splitlines():
        d = dong.strip()
        if d.startswith(ten + ":"):
            return d.split(":", 1)[1].strip().strip('"').strip("'")
    return ""


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("dung: render-config.py <template> <config-ra> [--tu-config]\n")
        return 2
    template, dich = argv[1], argv[2]
    tu_config = "--tu-config" in argv[3:]

    key_file = os.environ.get("CLIPROXY_KEY_FILE") or KEY_FILE_MAC_DINH
    khoa_file = doc_khoa_tu_file(key_file)
    khoa_secret = os.environ.get("CLIPROXY_API_KEY", "").strip()
    khoa = gop_khoa(khoa_file, khoa_secret)
    if not khoa:
        raise SystemExit(
            "khong co khoa nao: %s rong/khong doc duoc va CLIPROXY_API_KEY cung rong" % key_file
        )

    mgmt = os.environ.get("CLIPROXY_MGMT_KEY", "")
    dsn = os.environ.get("CHAT_HISTORY_DSN", "")
    if tu_config:
        # Chay tay tren server: lay lai gia tri cu thay vi doi nguoi dung dat secret.
        mgmt = mgmt or gia_tri_tu_config(dich, "secret-key")
        dsn = dsn or gia_tri_tu_config(dich, "chat-history-dsn")
    if not mgmt:
        raise SystemExit("thieu CLIPROXY_MGMT_KEY (hoac dung --tu-config de lay lai tu config.yaml)")

    tho = pathlib.Path(template).read_text(encoding="utf-8")
    tho = tho.replace("__MANAGEMENT_KEY__", mgmt).replace("__CHAT_HISTORY_DSN__", dsn)
    tho = thay_api_keys(tho, khoa)
    # Chi soi dong LENH, bo dong chu thich: phan dau template GIAI THICH cac
    # placeholder nen chinh chu thich do chua chuoi __API_KEY__ — lop loi
    # "tu to giac" da lam CI do mot lan.
    for dong in tho.splitlines():
        if dong.lstrip().startswith("#"):
            continue
        for gc in ("__API_KEY__", "__MANAGEMENT_KEY__", "__CHAT_HISTORY_DSN__"):
            if gc in dong:
                raise SystemExit(
                    "config.yaml van con placeholder %s — kiem tra lai template/secret" % gc
                )

    p = pathlib.Path(dich)
    p.write_text(tho, encoding="utf-8")
    p.chmod(0o600)
    # KHONG in khoa ra: log GitHub Actions khong xoa duoc.
    canh_bao = ""
    if khoa_secret and khoa_file and khoa_secret not in khoa_file:
        canh_bao = " (khoa trong secret KHAC file dung chung — da them ca hai)"
    sys.stderr.write(
        "render-config: %d khoa (%d tu %s, %s secret)%s -> %s\n"
        % (len(khoa), len(khoa_file), key_file, "co" if khoa_secret else "khong",
           canh_bao, dich)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
