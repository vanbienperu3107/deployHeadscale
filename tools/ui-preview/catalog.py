#!/usr/bin/env python3
"""P1 — Sinh trang muc luc ui-preview/index.html tu cac prototype.json.

Cau truc:
  ui-preview/<slug>/v<N>/index.html       prototype (duong dan TUONG DOI toi ../../_system/)
  ui-preview/<slug>/v<N>/prototype.json   manifest (xem REQUIRED ben duoi)
  ui-preview/<slug>/v<N>/approved/        baseline P5 (neu da duyet)

Dung:
  python3 tools/ui-preview/catalog.py           # ghi lai index.html
  python3 tools/ui-preview/catalog.py --check   # CI: loi neu manifest sai hoac index.html cu
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "ui-preview"
INDEX = ROOT / "index.html"
REQUIRED = {"title": str, "summary": str, "status": str, "created": str}
STATUSES = {"draft": "Chờ duyệt", "approved": "Đã duyệt", "superseded": "Đã thay thế", "rejected": "Không dùng"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VERSION = re.compile(r"^v([1-9][0-9]*)$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load() -> tuple[list[dict], list[str]]:
    protos, errors = [], []
    for manifest in sorted(ROOT.glob("*/v*/prototype.json")):
        vdir = manifest.parent
        slug, ver = vdir.parent.name, vdir.name
        where = f"{slug}/{ver}"
        vmatch = VERSION.match(ver)
        if not SLUG.match(slug) or vmatch is None:
            errors.append(f"{where}: ten thu muc phai la <slug-kebab>/v<N>")
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{where}/prototype.json: JSON loi: {e}")
            continue
        for key, typ in REQUIRED.items():
            if not isinstance(data.get(key), typ) or not data.get(key):
                errors.append(f"{where}/prototype.json: thieu '{key}'")
        if data.get("status") not in STATUSES:
            errors.append(f"{where}: status phai la mot trong {sorted(STATUSES)}")
        if data.get("created") and not DATE.match(data["created"]):
            errors.append(f"{where}: created phai dang YYYY-MM-DD")
        if not (vdir / "index.html").is_file():
            errors.append(f"{where}: thieu index.html")
        variants = data.get("variants", [])
        if not isinstance(variants, list) or any(not isinstance(v, dict) or "id" not in v for v in variants):
            errors.append(f"{where}: variants phai la list {{id, label}}")
            variants = []
        approved = vdir / "approved" / "approved.json"
        if data.get("status") == "approved" and not approved.is_file():
            errors.append(f"{where}: status=approved nhung chua co approved/approved.json (chay workflow UI preview approve)")
        data.update(slug=slug, version=int(vmatch.group(1)), path=f"{slug}/{ver}/",
                    has_baseline=approved.is_file(), variants=variants)
        protos.append(data)
    return protos, errors


def render(protos: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for p in protos:
        groups.setdefault(p["slug"], []).append(p)
    for g in groups.values():
        g.sort(key=lambda p: -p["version"])
    order = sorted(groups, key=lambda s: max(p["created"] for p in groups[s]), reverse=True)

    e = html.escape
    rows = []
    for slug in order:
        versions = groups[slug]
        head = versions[0]
        items = []
        for p in versions:
            variants = ", ".join(f"{v['id'].upper()} {v.get('label', '')}".strip() for v in p["variants"])
            baseline = f' · <a href="{e(p["path"])}approved/">ảnh chuẩn</a>' if p["has_baseline"] else ""
            items.append(
                f'<li class="ver ver--{e(p["status"])}"><a class="ver-link" href="{e(p["path"])}">v{p["version"]}</a>'
                f'<span class="status">{e(STATUSES[p["status"]])}</span>'
                f'<span class="when">{e(p["created"])}</span>'
                f'<span class="desc">{e(p["summary"])}'
                + (f'<br><small>Phương án: {e(variants)}</small>' if variants else "")
                + f'{baseline}</span></li>'
            )
        rows.append(
            f'<section class="proto" id="{e(slug)}"><h2>{e(head["title"])}</h2>'
            f'<p class="slug"><code>{e(slug)}</code></p><ol class="versions" reversed>{"".join(items)}</ol></section>'
        )
    body = "".join(rows) or '<p class="empty">Chưa có prototype nào. Tạo thư mục <code>&lt;slug&gt;/v1/</code> kèm <code>prototype.json</code>.</p>'
    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="tools/ui-preview/catalog.py">
<title>Prototype giao diện</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="_system/tokens.css">
<style>
body {{ margin:0; background:var(--md-sys-color-surface); color:var(--md-sys-color-on-surface); font:var(--md-sys-typescale-body-large); }}
main {{ max-width:760px; margin:0 auto; padding:40px 20px 64px; }}
h1 {{ margin:0 0 8px; font:var(--md-sys-typescale-headline-medium); }}
.lede {{ margin:0 0 32px; color:var(--md-sys-color-on-surface-variant); max-width:60ch; }}
.proto {{ padding:20px 0; border-top:1px solid var(--md-sys-color-outline-variant); }}
.proto h2 {{ margin:0; font:var(--md-sys-typescale-title-large); }}
.slug {{ margin:2px 0 12px; color:var(--md-sys-color-on-surface-variant); font:var(--md-sys-typescale-body-small); }}
.versions {{ list-style:none; margin:0; padding:0; }}
.ver {{ display:grid; grid-template-columns:48px 96px 1fr; gap:4px 12px; padding:10px 0; align-items:baseline; }}
.ver + .ver {{ opacity:.72; }}
.ver-link {{ font:var(--md-sys-typescale-title-medium); color:var(--md-sys-color-primary); }}
.status {{ font:var(--md-sys-typescale-label-medium); padding:2px 8px; border-radius:var(--md-sys-shape-corner-small); background:var(--md-sys-color-surface-container-high); justify-self:start; }}
.ver--approved .status {{ background:var(--md-sys-color-primary-container); color:var(--md-sys-color-on-primary-container); }}
.ver--draft .status {{ background:var(--md-sys-color-tertiary-container); color:var(--md-sys-color-on-tertiary-container); }}
.when {{ grid-column:2; grid-row:2; font:var(--md-sys-typescale-body-small); color:var(--md-sys-color-on-surface-variant); }}
.desc {{ grid-column:3; grid-row:1 / span 2; font:var(--md-sys-typescale-body-medium); }}
.desc small {{ color:var(--md-sys-color-on-surface-variant); }}
a {{ color:var(--md-sys-color-primary); }}
@media (max-width:520px) {{ .ver {{ grid-template-columns:48px 1fr; }} .when {{ grid-column:2; grid-row:auto; }} .desc {{ grid-column:1 / -1; grid-row:auto; }} }}
</style>
</head>
<body>
<main>
<h1>Prototype giao diện</h1>
<p class="lede">Bản mới nhất của mỗi prototype nằm trên cùng. Mở một phiên bản, bật “Góp ý” để ghi chú trực tiếp lên màn hình, rồi dán Markdown vào chat.</p>
{body}
</main>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    protos, errors = load()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    out = render(protos)
    if args.check:
        if not INDEX.is_file() or INDEX.read_text(encoding="utf-8") != out:
            print("ui-preview/index.html cu — chay tools/ui-preview/catalog.py", file=sys.stderr)
            return 1
        print(f"catalog OK ({len(protos)} prototype)")
        return 0
    INDEX.write_text(out, encoding="utf-8")
    print(f"Da ghi {INDEX} ({len(protos)} prototype)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
