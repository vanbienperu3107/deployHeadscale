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
\trequest_header -X-Auth-Email
\tforward_auth derp-backend:8787 {
\t\turi /api/auth/forward
\t\tcopy_headers X-Auth-Email
\t\t@unauth status 401 404
\t\thandle_response @unauth {
\t\t\tredir https://cms.hangocthanh.io.vn/app/sign-in 302
\t\t}
\t}
\treverse_proxy beszel:8090
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
