"""Test block Caddy status.hangocthanh.io.vn (beszel/caddy_block.py).

Su co 2026-09-14: thu tu directive mac dinh cua Caddy chay forward_auth TRUOC
request_header, nen `request_header -X-Auth-Email` xoa mat header SSO vua chep
tu derp-backend -> Beszel khong nhan email, luon hien trang login.
"""
import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CADDY_IMAGE = "caddy:2.8.4"  # cung ban memory-caddy tren vpn6

spec = importlib.util.spec_from_file_location("caddy_block", ROOT / "beszel" / "caddy_block.py")
caddy_block = importlib.util.module_from_spec(spec)
spec.loader.exec_module(caddy_block)
BLOCK = caddy_block.BLOCK


def test_sso_nam_trong_route_de_giu_thu_tu():
    route_at = BLOCK.index("\troute {")
    delete_at = BLOCK.index("request_header -X-Auth-Email")
    forward_at = BLOCK.index("forward_auth derp-backend:8787")
    proxy_at = BLOCK.index("reverse_proxy beszel:8090")
    assert route_at < delete_at < forward_at < proxy_at


def test_forward_auth_chep_dung_header_va_redirect_khi_401():
    assert "copy_headers X-Auth-Email" in BLOCK
    assert "uri /api/auth/forward" in BLOCK
    assert "@unauth status 401 404" in BLOCK
    assert "redir https://cms.hangocthanh.io.vn/app/sign-in 302" in BLOCK


def test_ngoac_can_bang():
    assert BLOCK.count("{") == BLOCK.count("}")


def test_replace_thay_block_cu_va_idempotent():
    old = "a.example {\n\trespond ok\n}\n\nstatus.hangocthanh.io.vn {\n\trequest_header -X-Auth-Email\n\tforward_auth x {\n\t}\n}\n\nb.example {\n\trespond b\n}\n"
    once = caddy_block.replace(old)
    assert once.count("status.hangocthanh.io.vn {") == 1
    assert "\troute {" in once
    assert "a.example {" in once and "b.example {" in once
    assert caddy_block.replace(once) == once


def test_replace_noi_vao_cuoi_khi_chua_co():
    out = caddy_block.replace("a.example {\n\trespond ok\n}\n")
    assert out.startswith("a.example {")
    assert out.rstrip().endswith("}")
    assert "status.hangocthanh.io.vn {" in out


def _handlers(node):
    """Duyet JSON Caddy, tra ve danh sach handler theo dung thu tu thuc thi."""
    out = []
    if isinstance(node, dict):
        if "handler" in node:
            out.append(node)
        for key in ("routes", "handle", "subroute"):
            if key in node and key != "handle_response":
                out.extend(_handlers(node[key]))
    elif isinstance(node, list):
        for item in node:
            out.extend(_handlers(item))
    return out


@pytest.mark.skipif(shutil.which("docker") is None, reason="can docker de chay caddy adapt")
def test_caddy_adapt_xoa_header_truoc_forward_auth(tmp_path):
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("{\n\tauto_https off\n}\n\n" + BLOCK, encoding="utf-8")
    res = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{caddyfile}:/etc/caddy/Caddyfile:ro", CADDY_IMAGE,
         "caddy", "adapt", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
        capture_output=True, text=True, timeout=300,
    )
    assert res.returncode == 0, res.stderr
    cfg = json.loads(res.stdout)
    # servers la dict {"srv0": {...}} -> duyet tung server theo thu tu
    flat = _handlers(list(cfg["apps"]["http"]["servers"].values()))

    def idx(pred):
        hits = [i for i, h in enumerate(flat) if pred(h)]
        assert hits, "khong tim thay handler"
        return hits[0]

    delete_i = idx(lambda h: h["handler"] == "headers"
                   and "X-Auth-Email" in h.get("request", {}).get("delete", []))
    forward_i = idx(lambda h: h["handler"] == "reverse_proxy"
                    and h.get("rewrite", {}).get("uri") == "/api/auth/forward")
    beszel_i = idx(lambda h: h["handler"] == "reverse_proxy"
                   and any(u.get("dial") == "beszel:8090" for u in h.get("upstreams", [])))
    assert delete_i < forward_i < beszel_i, (delete_i, forward_i, beszel_i)
