#!/usr/bin/env python3
"""In ra Caddyfile moi voi block status.hangocthanh.io.vn da thay (stdout).

Goi: python3 caddy_block.py <Caddyfile> > tmp ; cat tmp > <Caddyfile>
(cat > giu inode — Caddyfile la bind-mount FILE, doi inode thi container doc ban cu.)
Idempotent: block cu (bat ky noi dung) bi thay, chua co thi noi vao cuoi.
"""
import re
import sys

HOST = "status.hangocthanh.io.vn"
BLOCK = """status.hangocthanh.io.vn {
\t# SSO tu CMS: xoa header client tu gui, hoi derp-backend xem phien CMS con
\t# hop le khong; hop le -> chep X-Auth-Email (Beszel TRUSTED_AUTH_HEADER).
\t# PHAI boc route{}: thu tu mac dinh cua Caddy chay forward_auth TRUOC
\t# request_header -> header vua chep bi xoa, Beszel luon hien trang login
\t# (su co 2026-09-14). route{} giu dung thu tu viet.
\troute {
\t\trequest_header -X-Auth-Email
\t\tforward_auth derp-backend:8787 {
\t\t\turi /api/auth/forward
\t\t\tcopy_headers X-Auth-Email
\t\t\t@unauth status 401 404
\t\t\thandle_response @unauth {
\t\t\t\tredir https://cms.hangocthanh.io.vn/app/sign-in 302
\t\t\t}
\t\t}
\t\treverse_proxy beszel:8090
\t}
\t# Trang Monitor cua CMS nhung iframe: chi cho cms.* frame, site la thi khong.
\theader -X-Frame-Options
\theader ?Content-Security-Policy "frame-ancestors 'self' https://cms.hangocthanh.io.vn"
}
"""


def replace(text: str) -> str:
    start = re.search(r"(?m)^" + re.escape(HOST) + r"\s*\{", text)
    if not start:
        return text.rstrip("\n") + "\n\n# Beszel (deployHeadscale/beszel)\n" + BLOCK
    depth, i = 0, start.end() - 1
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    else:
        sys.exit("block %s khong dong ngoac" % HOST)
    end = i + 1
    if end < len(text) and text[end] == "\n":
        end += 1
    return text[: start.start()] + BLOCK + text[end:]


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        sys.stdout.write(replace(f.read()))
