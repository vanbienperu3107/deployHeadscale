"""Kiem tra tinh toan ven cua ui-preview/ (prototype giao dien).

Chay: python -m pytest -q test/test_ui_preview.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI = REPO / "ui-preview"
TOOLS = REPO / "tools" / "ui-preview"
PROTOTYPES = sorted(p.parent for p in UI.glob("*/v*/prototype.json"))
REF = re.compile(r'(?:href|src)="([^"#?]+)')


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True)


def test_co_it_nhat_mot_prototype():
    assert PROTOTYPES, "ui-preview/ phai co it nhat mot <slug>/v<N>/prototype.json"


def test_catalog_index_khop_manifest():
    r = run(str(TOOLS / "catalog.py"), "--check")
    assert r.returncode == 0, r.stderr


def test_khong_con_file_rac_o_goc_ui_preview():
    # Goc chi gom catalog + _system + thu muc prototype -> moi prototype deu co phien ban.
    allowed = {"index.html", "_system"}
    extra = [p.name for p in UI.iterdir() if p.name not in allowed and not (p.is_dir() and any(p.glob("v*/prototype.json")))]
    assert not extra, f"File/thu muc khong thuoc prototype nao o goc ui-preview/: {extra}"


def test_duong_dan_noi_bo_la_tuong_doi_va_ton_tai():
    # Preview duoc phuc vu duoi prefix /preview-<run>/ -> duong dan tuyet doi "/..." se hong.
    for html in UI.rglob("*.html"):
        for ref in REF.findall(html.read_text(encoding="utf-8")):
            if ref.startswith(("http://", "https://", "data:", "mailto:")):
                continue
            assert not ref.startswith("/"), f"{html.relative_to(REPO)}: duong dan tuyet doi '{ref}'"
            target = (html.parent / ref).resolve()
            if ref.endswith("/"):
                target = target / "index.html"
            assert target.exists(), f"{html.relative_to(REPO)}: '{ref}' khong ton tai"


def test_prototype_moi_dung_design_system():
    for vdir in PROTOTYPES:
        manifest = json.loads((vdir / "prototype.json").read_text(encoding="utf-8"))
        if manifest.get("variants"):
            html = (vdir / "index.html").read_text(encoding="utf-8")
            for asset in ("_system/tokens.css", "_system/variants.js", "_system/feedback.js"):
                assert asset in html, f"{vdir.relative_to(REPO)} co variants nhung khong nap {asset}"
            for v in manifest["variants"]:
                assert f'data-variant="{v["id"]}"' in html, f"{vdir.relative_to(REPO)}: thieu section data-variant={v['id']}"


def test_baseline_du_anh_theo_approved_json():
    for approved in UI.glob("*/v*/approved/approved.json"):
        rec = json.loads(approved.read_text(encoding="utf-8"))
        for key in ("prototype", "approvedAt", "sourceCommit", "environment", "viewports"):
            assert rec.get(key), f"{approved.relative_to(REPO)} thieu '{key}'"
        cases = rec.get("variants") or [None]
        for vp in rec["viewports"]:
            for v in cases:
                png = approved.parent / f"{vp['name']}{'-' + v if v else ''}.png"
                assert png.is_file(), f"thieu anh chuan {png.relative_to(REPO)}"


def test_tokens_co_du_vai_tro_m3_light_dark():
    css = (UI / "_system" / "tokens.css").read_text(encoding="utf-8")
    light = css[css.index(':root, [data-theme="light"]'):css.index('[data-theme="dark"]')]
    dark = css[css.index('[data-theme="dark"]'):css.index("END GENERATED COLORS")]
    for role in ("primary", "on-primary", "surface", "on-surface", "outline", "error", "surface-container-highest"):
        assert f"--md-sys-color-{role}:" in light, f"light thieu {role}"
        assert f"--md-sys-color-{role}:" in dark, f"dark thieu {role}"
    assert "--md-sys-color-primary: #1a6b51;" in light  # primaryLight trong adroidClient Color.kt
    assert "--md-sys-color-primary: #8ad6b6;" in dark   # primaryDark


def test_sync_tokens_sinh_dung_tu_color_kt(tmp_path):
    kt = tmp_path / "Color.kt"
    roles = re.findall(r"--md-sys-color-([a-z-]+):", (UI / "_system" / "tokens.css").read_text(encoding="utf-8"))
    camel = sorted({re.sub(r"-([a-z])", lambda m: m.group(1).upper(), r) for r in roles})
    kt.write_text("\n".join(f"val {r}{mode} = Color(0xFF{i:06X})" for i, r in enumerate(camel) for mode in ("Light", "Dark")))
    r = run(str(TOOLS / "sync_tokens.py"), str(kt), "--check")
    assert r.returncode == 1, "check phai FAIL khi Color.kt khac tokens.css"
