"""Validate stack cliproxy (CLIProxyAPI tren vpn4) - chay trong CI truoc deploy.

Cac bat bien duoc bao ve o day:
  1. Token OAuth Claude/Codex phai nam tren bind mount ./auths -> deploy lai
     KHONG mat dang nhap.
  2. Duong dan auth-dir trong config phai trung dich cua bind mount, neu lech
     thi token ghi vao lop ghi cua container va bien mat khi recreate.
  3. Cong 8317 mo cong khai nen api-keys BAT BUOC phai co.
  4. Cac cong callback OAuth chi duoc bind loopback (chi dung qua SSH tunnel).
  5. Image phai pin tag (khong :latest troi noi) de deploy tai lap duoc.
"""
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).parent.parent
COMPOSE = ROOT / "cliproxy" / "docker-compose.yml"
TEMPLATE = ROOT / "cliproxy" / "config.template.yaml"
GITIGNORE = ROOT / "cliproxy" / ".gitignore"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cliproxy.yml"
INTEGRATION = ROOT / "test" / "cliproxy_integration.sh"

AUTH_DIR_IN_CONTAINER = "/root/.cli-proxy-api"
# Cong ben trong container (mac dinh cua CLIProxyAPI, = port trong config.yaml).
CONTAINER_PORT = "8317"
# Cong publish ra ngoai: co tinh KHAC mac dinh de bot quet cong mac dinh khong thay.
PUBLIC_PORT = "28417"


def load_compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def load_template():
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def service():
    return load_compose()["services"]["cliproxy"]


def image_default():
    """Lay tag mac dinh trong ${CLIPROXY_IMAGE:-<default>}."""
    raw = service()["image"]
    m = re.match(r"^\$\{CLIPROXY_IMAGE:-(.+)\}$", raw)
    assert m, f"image phai co dang ${{CLIPROXY_IMAGE:-<tag mac dinh>}}, dang co: {raw}"
    return m.group(1)


# ---------- docker-compose ----------

def test_compose_hop_le_va_co_service_cliproxy():
    cfg = load_compose()
    assert "cliproxy" in cfg["services"], "compose phai co service ten 'cliproxy'"
    assert service()["container_name"] == "cliproxy"
    assert service()["restart"] == "unless-stopped", "phai tu chay lai khi vpn4 reboot"


def test_image_pin_tag_khong_dung_latest():
    img = image_default()
    assert ":" in img, f"image phai pin tag cu the: {img}"
    tag = img.rsplit(":", 1)[1]
    assert tag != "latest", "khong dung :latest — deploy phai tai lap duoc"
    assert re.match(r"^v\d+\.\d+\.\d+$", tag), f"tag nen dang vX.Y.Z, dang co: {tag}"


def test_auths_la_bind_mount_de_token_song_qua_deploy():
    vols = service()["volumes"]
    auth_mounts = [v for v in vols if v.split(":")[1] == AUTH_DIR_IN_CONTAINER]
    assert len(auth_mounts) == 1, f"phai co dung 1 mount toi {AUTH_DIR_IN_CONTAINER}: {vols}"
    src = auth_mounts[0].split(":")[0]
    assert src.startswith("./"), (
        f"auths phai la bind mount tuong doi (de backup/di chuyen server), dang co: {src}"
    )


def test_config_yaml_duoc_mount_vao_container():
    vols = service()["volumes"]
    assert any(v.split(":")[1] == "/CLIProxyAPI/config.yaml" for v in vols), (
        f"phai mount config.yaml vao /CLIProxyAPI/config.yaml: {vols}"
    )


def test_publish_cong_la_cong_it_dung_khong_phai_mac_dinh():
    """Doi cong ngoai la de bot quet danh sach cong mac dinh khong tim thay dich vu.
    Neu vo tinh publish lai 8317 thi tac dung do mat sach.
    """
    ports = service()["ports"]
    assert f"{PUBLIC_PORT}:{CONTAINER_PORT}" in ports, (
        f"phai publish {PUBLIC_PORT} -> {CONTAINER_PORT}: {ports}"
    )
    assert f"{CONTAINER_PORT}:{CONTAINER_PORT}" not in ports, (
        f"khong duoc publish cong mac dinh {CONTAINER_PORT} ra ngoai: {ports}"
    )
    assert int(PUBLIC_PORT) < 32768, (
        f"{PUBLIC_PORT} nam trong dai ephemeral (32768-60999) cua vpn4 -> co the "
        "dung voi cong nguon cua ket noi di ra"
    )


def test_cong_api_mo_cong_khai_con_callback_chi_loopback():
    ports = service()["ports"]
    callback_ports = {"54545", "1455", "8085"}
    for p in ports:
        parts = p.split(":")
        if len(parts) == 3:
            host_ip, host_port, _ = parts
            if host_port in callback_ports:
                assert host_ip == "127.0.0.1", (
                    f"cong callback OAuth {host_port} phai bind 127.0.0.1, dang co: {p}"
                )
        else:
            host_port = parts[0]
            assert host_port not in callback_ports, (
                f"cong callback OAuth {host_port} dang mo cong khai ({p}) — phai bind 127.0.0.1"
            )


def test_callback_claude_va_codex_deu_co_mat():
    """Thieu 1 trong 2 cong nay thi khong login duoc qua SSH tunnel."""
    ports = " ".join(service()["ports"])
    assert "54545" in ports, "thieu cong callback 54545 (Claude Code)"
    assert "1455" in ports, "thieu cong callback 1455 (OpenAI Codex)"


def test_gioi_han_bo_nho_vi_vpn4_chi_2gb():
    assert "mem_limit" in service(), (
        "vpn4 chi co 2GB RAM va dang chay derper + vpn-gw -> phai dat mem_limit"
    )


def test_healthcheck_khong_phu_thuoc_curl():
    """Image cli-proxy-api dua tren debian:bookworm, khong cai curl/wget."""
    hc = service()["healthcheck"]["test"]
    joined = " ".join(hc)
    assert "curl" not in joined and "wget" not in joined, (
        f"healthcheck khong duoc dung curl/wget (image khong co): {hc}"
    )
    assert "/dev/tcp" in joined, f"healthcheck nen dung /dev/tcp cua bash: {hc}"


# ---------- config template ----------

def test_template_la_yaml_hop_le_va_dung_cong():
    cfg = load_template()
    assert str(cfg["port"]) == CONTAINER_PORT, (
        f"port trong config phai la cong BEN TRONG container ({CONTAINER_PORT}), "
        "khong phai cong publish ra ngoai"
    )


def test_cong_publish_khong_lech_giua_compose_workflow_va_integration():
    """Doi cong o compose ma quen doi cho verify -> deploy 'xanh gia' hoac that bai
    kho hieu. Rang buoc 3 file phai noi cung mot con so.
    """
    wf = WORKFLOW.read_text(encoding="utf-8")
    sh = INTEGRATION.read_text(encoding="utf-8")
    for name, body in (("deploy-cliproxy.yml", wf), ("cliproxy_integration.sh", sh)):
        assert f":{PUBLIC_PORT}/" in body, (
            f"{name} phai goi vao cong publish {PUBLIC_PORT}"
        )
        # Cong mac dinh chi duoc xuat hien o phep thu "phai khong ket noi duoc"
        # (dong do luon co '000'), khong duoc dung lam endpoint that.
        for line in body.splitlines():
            if f":{CONTAINER_PORT}/" in line:
                assert "000" in line, (
                    f"{name} con goi vao cong {CONTAINER_PORT} nhu endpoint that: "
                    f"{line.strip()!r}"
                )


def test_auth_dir_khop_voi_bind_mount():
    """Lech duong dan nay = token ghi nham cho, mat sau moi lan recreate."""
    cfg = load_template()
    assert cfg["auth-dir"] == AUTH_DIR_IN_CONTAINER, (
        f"auth-dir phai la {AUTH_DIR_IN_CONTAINER} de khop bind mount ./auths, "
        f"dang co: {cfg['auth-dir']}"
    )


def test_bat_buoc_co_api_key_vi_cong_8317_mo_cong_khai():
    cfg = load_template()
    keys = cfg.get("api-keys") or []
    assert len(keys) >= 1, "8317 mo ra Internet ma khong co api-keys = ai cung goi duoc"
    assert all(isinstance(k, str) and k.strip() for k in keys), "api-keys khong duoc rong"


def test_template_chi_chua_placeholder_khong_chua_key_that():
    raw = TEMPLATE.read_text(encoding="utf-8")
    cfg = load_template()
    assert cfg["api-keys"] == ["__API_KEY__"], (
        "template phai giu placeholder __API_KEY__, khong duoc commit key that"
    )
    assert cfg["remote-management"]["secret-key"] == "__MANAGEMENT_KEY__", (
        "template phai giu placeholder __MANAGEMENT_KEY__"
    )
    assert "sk-" not in raw, "phat hien chuoi giong API key that trong template"


def test_management_api_khong_mo_ra_internet():
    cfg = load_template()
    assert cfg["remote-management"]["allow-remote"] is False, (
        "Management API chi duoc dung tu localhost cua vpn4 (qua SSH)"
    )


def test_log_bi_gioi_han_dung_luong():
    """vpn4 chi con ~37GB dia va con chay derper — log phai co tran."""
    cfg = load_template()
    assert cfg["logging-to-file"] is True
    assert cfg["logs-max-total-size-mb"] > 0, "phai gioi han tong dung luong log"


# ---------- gitignore / workflow ----------

def test_gitignore_chan_config_va_token():
    body = GITIGNORE.read_text(encoding="utf-8")
    assert "config.yaml" in body, "config.yaml (chua API key) phai bi gitignore"
    assert "auths/" in body, "auths/ (token OAuth) phai bi gitignore"


def test_config_yaml_that_chua_bao_gio_bi_commit():
    assert not (ROOT / "cliproxy" / "config.yaml").exists(), (
        "cliproxy/config.yaml chua secret — khong duoc ton tai trong repo"
    )
    assert not (ROOT / "cliproxy" / "auths").exists(), (
        "cliproxy/auths chua token OAuth — khong duoc ton tai trong repo"
    )


def test_workflow_deploy_khong_xoa_auths():
    """Deploy lai KHONG duoc lam mat dang nhap Claude/Codex."""
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "rm -rf auths" not in body and "docker compose down -v" not in body, (
        "workflow deploy khong duoc xoa auths/ hoac volume"
    )
    assert "git clean" not in body, "git clean se xoa auths/ (untracked) tren vpn4"


def test_workflow_khong_dung_heredoc_trong_script_ssh():
    """Bay da dinh that (run 30751552305): appleboy/ssh-action chen dong
    'DRONE_SSH_PREV_COMMAND_EXIT_CODE=$? ; ...' sau MOI dong cua script, nen than
    heredoc bi chen rac -> python bao SyntaxError. Moi lenh phai gon trong 1 dong.
    """
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in wf["jobs"]["deploy"]["steps"]:
        uses = step.get("uses", "")
        if not uses.startswith("appleboy/ssh-action"):
            continue
        script = step["with"]["script"]
        assert "<<" not in script, (
            "script cua ssh-action khong duoc dung heredoc (<<EOF/<<'PY') — "
            "ssh-action chen dong kiem tra exit code vao giua heredoc"
        )


def test_workflow_khong_dung_else_trong_script_ssh():
    """Bay thu hai (run 30751710639): dong kiem tra exit code duoc chen NGAY SAU
    dong 'else', luc do $? van la ket qua cua dieu kien if (=1 khi dieu kien sai)
    -> script thoat 1 vo co du chua chay lenh nao trong nhanh else. Viet lai bang
    lenh mot dong hoac nhieu khoi if rieng.
    """
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in wf["jobs"]["deploy"]["steps"]:
        if not step.get("uses", "").startswith("appleboy/ssh-action"):
            continue
        for line in step["with"]["script"].splitlines():
            stripped = line.strip()
            assert stripped != "else" and not stripped.startswith("elif "), (
                f"script cua ssh-action khong duoc co nhanh else/elif: {line!r}"
            )


def test_workflow_dung_chung_concurrency_group_voi_stack_vpn4_khac():
    """derper/vpn-gw cung o vpn4 — deploy song song de dinh lock docker/dpkg."""
    body = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert body["concurrency"]["group"] == "deploy-vpn4-host"
