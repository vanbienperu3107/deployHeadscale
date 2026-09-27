"""Khoa API cua CLIProxy lay tu FILE DUNG CHUNG tren vpn4.

SU CO 2026-09-26/27: khoa them tay qua trang /management.html bi lan deploy sau
xoa sach — config.yaml duoc sinh lai tu template + secret — nen OpenCode dinh
401 "Invalid API key" hai lan lien tiep, lan sau ngay sau khi vua sua xong lan
truoc. Nguon khoa gio la FILE /opt/opencode/secrets/cliproxy.key, chinh file ma
opencode-server mount vao /run/secrets/cliproxy-key: mot file, ca hai ben doc.
"""
import importlib.util
import os
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).parent.parent
TEMPLATE = ROOT / "cliproxy" / "config.template.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cliproxy.yml"

_spec = importlib.util.spec_from_file_location(
    "render_config", ROOT / "cliproxy" / "render-config.py"
)
render_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_config)


def test_khoa_mac_dinh_tro_dung_file_opencode_mount():
    """Lech duong dan nay = hai ben doc hai khoa khac nhau, va trieu chung chi lo
    ra khi goi model (401), khong lo luc deploy."""
    assert render_config.KEY_FILE_MAC_DINH == "/opt/opencode/secrets/cliproxy.key"


def test_doc_khoa_bo_dong_trong_va_chu_thich(tmp_path):
    f = tmp_path / "keys.txt"
    f.write_text("# ghi chu\nsk-mot\n\n  sk-hai  \n", encoding="utf-8")
    assert render_config.doc_khoa_tu_file(str(f)) == ["sk-mot", "sk-hai"]


def test_doc_khoa_file_khong_ton_tai_thi_rong(tmp_path):
    assert render_config.doc_khoa_tu_file(str(tmp_path / "chua-co")) == []


def test_gop_khoa_giu_thu_tu_va_bo_trung():
    assert render_config.gop_khoa(["a", "b"], "a") == ["a", "b"]
    assert render_config.gop_khoa(["a"], "b") == ["a", "b"]
    assert render_config.gop_khoa([], "b") == ["b"]


def test_thay_khoi_api_keys_giu_nguyen_phan_con_lai():
    tho = 'port: 8317\napi-keys:\n  - "__API_KEY__"\n\ndebug: false\n'
    ra = render_config.thay_api_keys(tho, ["sk-mot", "sk-hai"])
    cfg = yaml.safe_load(ra)
    assert cfg["api-keys"] == ["sk-mot", "sk-hai"]
    assert cfg["port"] == 8317 and cfg["debug"] is False
    assert "__API_KEY__" not in ra


def _render(tmp_path, monkeypatch, noi_dung_file, secret):
    keys = tmp_path / "cliproxy.key"
    if noi_dung_file is not None:
        keys.write_text(noi_dung_file, encoding="utf-8")
    dich = tmp_path / "config.yaml"
    monkeypatch.setenv("CLIPROXY_KEY_FILE", str(keys))
    monkeypatch.setenv("CLIPROXY_API_KEY", secret)
    monkeypatch.setenv("CLIPROXY_MGMT_KEY", "mgmt-test")
    monkeypatch.setenv("CHAT_HISTORY_DSN", "")
    ma = render_config.main(["render-config.py", str(TEMPLATE), str(dich)])
    return ma, dich


def test_render_lay_khoa_tu_file_va_them_khoa_secret(tmp_path, monkeypatch):
    ma, dich = _render(tmp_path, monkeypatch, "sk-tren-server\n", "sk-trong-secret")
    assert ma == 0
    cfg = yaml.safe_load(dich.read_text(encoding="utf-8"))
    assert cfg["api-keys"] == ["sk-tren-server", "sk-trong-secret"]
    assert cfg["remote-management"]["secret-key"] == "mgmt-test"


def test_render_khong_co_file_thi_dung_secret(tmp_path, monkeypatch):
    """May dung lan dau chua co file — deploy van phai chay duoc."""
    ma, dich = _render(tmp_path, monkeypatch, None, "sk-trong-secret")
    assert ma == 0
    cfg = yaml.safe_load(dich.read_text(encoding="utf-8"))
    assert cfg["api-keys"] == ["sk-trong-secret"]


def test_render_khong_co_khoa_nao_thi_dung_ngay(tmp_path, monkeypatch):
    """Config khong co khoa = cong 28417 mo toang ra Internet. Phai do ngay."""
    with pytest.raises(SystemExit):
        _render(tmp_path, monkeypatch, "", "")


def test_render_khong_in_khoa_ra_log(tmp_path, monkeypatch, capsys):
    """Log cua GitHub Actions khong xoa duoc."""
    _render(tmp_path, monkeypatch, "sk-tren-server\n", "sk-trong-secret")
    ra = capsys.readouterr()
    assert "sk-tren-server" not in (ra.out + ra.err)
    assert "sk-trong-secret" not in (ra.out + ra.err)


def test_render_quyen_file_chi_chu_so_huu_doc(tmp_path, monkeypatch):
    ma, dich = _render(tmp_path, monkeypatch, "sk-tren-server\n", "sk-trong-secret")
    assert ma == 0
    if os.name != "nt":
        assert oct(dich.stat().st_mode & 0o777) == "0o600"


def test_render_tu_config_lay_lai_mgmt_key_khi_chay_tay(tmp_path, monkeypatch):
    """Sua file khoa tren server roi chay lai KHONG can secret: mgmt key doc lai
    tu config.yaml dang co. Thieu duong nay thi doi khoa bang tay se tat trang
    quan tri (secret-key rong = tat han API do)."""
    dich = tmp_path / "config.yaml"
    keys = tmp_path / "cliproxy.key"
    keys.write_text("sk-mot\n", encoding="utf-8")
    monkeypatch.setenv("CLIPROXY_KEY_FILE", str(keys))
    monkeypatch.setenv("CLIPROXY_API_KEY", "")
    monkeypatch.setenv("CLIPROXY_MGMT_KEY", "mgmt-cu")
    monkeypatch.setenv("CHAT_HISTORY_DSN", "")
    assert render_config.main(["x", str(TEMPLATE), str(dich)]) == 0

    keys.write_text("sk-hai\n", encoding="utf-8")
    monkeypatch.delenv("CLIPROXY_MGMT_KEY")
    assert render_config.main(["x", str(TEMPLATE), str(dich), "--tu-config"]) == 0
    cfg = yaml.safe_load(dich.read_text(encoding="utf-8"))
    assert cfg["api-keys"] == ["sk-hai"]
    assert cfg["remote-management"]["secret-key"] == "mgmt-cu"


def test_workflow_dung_render_config_khong_con_thay_placeholder_bang_tay():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "render-config.py config.template.yaml config.yaml" in body, (
        "deploy phai sinh config qua render-config.py de lay khoa tu file dung chung"
    )
    assert "replace('__API_KEY__'" not in body, (
        "khong con thay __API_KEY__ bang secret nua — khoa den tu file tren server"
    )
