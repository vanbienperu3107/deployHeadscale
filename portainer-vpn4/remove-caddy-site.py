#!/usr/bin/env python3
"""Go site Portainer khoi Caddyfile cua edge-vpn4, theo RANH GIOI KHOI.

Vi sao khong so khop ca doan van ban: ban dau rollback nhung nguyen van than
site vao mot chuoi Python trong workflow. Chi can them mot dong comment hay doi
mot flag trong Caddyfile la `assert count == 1` vo hieu -> rollback chet giua
chung, sau khi da go route nginx nhung chua phuc hoi duoc Caddy.

Thay vao do: tim dong mo site, dem ngoac de xac dinh dong dong, roi cat dung
khoi do. Van FAIL-CLOSED: phai co DUNG MOT site khop, neu khong thi thoat loi
va khong ghi gi ca.
"""
from __future__ import annotations

import sys
from pathlib import Path

SITE_ADDRESS = "https://portainer.hangocthanh.io.vn:8447"


def find_site_bounds(lines: list[str]) -> tuple[int, int]:
    """Tra ve [start, end) cua khoi site, ke ca comment dinh ngay truoc no."""
    starts = [
        index
        for index, line in enumerate(lines)
        if line.lstrip().startswith(SITE_ADDRESS)
    ]
    if len(starts) != 1:
        raise SystemExit(
            f"expected exactly one '{SITE_ADDRESS}' site block, found {len(starts)}"
        )

    start = starts[0]
    if "{" not in lines[start]:
        raise SystemExit(f"site header at line {start + 1} does not open a block")

    depth = 0
    end = None
    for index in range(start, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        if depth == 0:
            end = index + 1
            break
    if end is None:
        raise SystemExit("unbalanced braces: site block never closes")

    # Nuot cac dong comment dinh lien ngay truoc header (tai lieu cua chinh site).
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    # Nuot dong trong ngay sau khoi de khong de lai hai dong trong lien tiep.
    while end < len(lines) and lines[end].strip() == "":
        end += 1

    return start, end


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: remove-caddy-site.py <Caddyfile>")

    path = Path(argv[1])
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    start, end = find_site_bounds(lines)
    remaining = "".join(lines[:start] + lines[end:])

    if SITE_ADDRESS in remaining:
        raise SystemExit("site address still present after removal")
    if remaining.count("{") != remaining.count("}"):
        raise SystemExit("removal would leave unbalanced braces; refusing to write")

    path.write_text(remaining, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
