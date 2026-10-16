"""Bao ve tinh READ-ONLY cua workflow khao sat vpn4.

vpn4 giu derper — relay DERP chinh cua ca tailnet. Mot lenh ghi lot vao workflow
"khao sat" se recreate container giua luc dang chay va lam moi peer mat relay.
Workflow nay duoc phep SSH vao may that, nen rao chan phai la test chu khong phai
loi hua trong comment.

⚠️ RAO CHAN LA ALLOWLIST, KHONG PHAI DENYLIST. Ban dau file nay dung danh sach
cam (`docker compose up`, `docker run`, ...) va no THUNG: `docker compose -f x.yml
up -d` — chinh la cach viet pho bien nhat trong repo nay — lot qua het, vi `up`
khong con dung ngay sau `compose`. Tuong tu `docker update --memory` (tai tao
dung su co OOM-kill cliproxy 2026-08-02) khong he co trong danh sach cam.
Denylist chi chan duoc nhung gi ta nho ra; allowlist chan moi thu ta chua nghi toi.

Bat bien:
  1. Moi lenh docker phai nam trong allowlist dong tu chi-doc.
  2. `docker exec` chi duoc chay lenh doc cau hinh, khong shell, khong noi lenh.
  3. Khong ghi file / khong sua repo / khong sua dich vu tren host.
  4. Dung chung concurrency group voi cac deploy vpn4 khac.
  5. Chi chay bang tay (workflow_dispatch).
  6. Dung secret cua vpn4; khong co duong in secret ra log.
  7. Khong duoc them `script_stop` (pha cac nhanh `else`), va `docker stats`
     phai co `--no-stream` (thieu la treo het command_timeout).
"""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "survey-docker-vpn4.yml"


def load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def ssh_steps():
    """MOI step SSH, trong MOI job.

    Khong duoc tra ve step dau tien roi dung: ban cu lam vay, nen them mot step
    ssh-action thu hai (viec rat tu nhien — "khao sat them muc 13") la script cua
    no khong bi kiem tra mot dong nao. Hard-code jobs["survey"] cung the: mot job
    SSH thu hai se vo hinh.
    """
    ds = []
    for job in load()["jobs"].values():
        for step in job.get("steps", []):
            if "ssh-action" in str(step.get("uses", "")):
                ds.append(step)
    assert ds, "Khong tim thay step ssh-action nao trong workflow khao sat"
    return ds


def ssh_step():
    """Step SSH duy nhat. Co y FAIL neu co nhieu hon mot."""
    ds = ssh_steps()
    assert len(ds) == 1, (
        f"Co {len(ds)} step ssh-action. Them step SSH la them mot duong chay lenh "
        "tren vpn4 — phai sua test de quet het truoc khi them."
    )
    return ds[0]


def ssh_script_raw():
    """Noi dung script chay TREN vpn4, NGUYEN VAN (ca comment), MOI step gop lai."""
    return "\n".join(s["with"]["script"] for s in ssh_steps())


def ssh_script():
    """Chi phan MA THUC THI: da bo dong comment.

    Bat buoc tach khoi ban nguyen van. Script nay giai thich tung bay bang
    comment, trong do co nhac ten chinh nhung lenh bi cam ("thieu --no-stream
    thi docker stats chay vo han", "docker compose up"). Quet ca comment thi
    test bao dong gia; te hon la nguoi sau se xoa comment de lam test xanh,
    tuc la xoa dung phan tri thuc dat nhat cua file.

    ⚠️ CHI bo dong comment tron ven, KHONG cat comment cuoi dong. Ban truoc cat
    tu `" #"` dau tien va do la mot lo thung: `echo "ghi chu # "; docker restart
    derper` — tren host, `#` nam trong ngoac kep la VAN BAN, con `; docker
    restart derper` CHAY THAT, nhung phep cat lam ca phan sau bien mat khoi tam
    nhin cua test. No con cat nham ca dong tieu de that (`echo "##### [1] ...`).
    Script nay khong dung comment cuoi dong, nen bo nhanh do la mat trang.
    """
    return "\n".join(
        dong for dong in ssh_script_raw().splitlines()
        if not dong.lstrip().startswith("#")
    )


def test_workflow_ton_tai_va_hop_le():
    assert WORKFLOW.is_file(), f"Thieu {WORKFLOW}"
    assert load()["jobs"]["survey"], "Thieu job 'survey'"


# ---------- bat bien 1: allowlist dong tu docker ----------

# Dong tu chi DOC trang thai. Bat ky thu gi ngoai day deu bi tu choi, ke ca khi
# no vo hai — them moi phai co y thuc va phai sua test.
#
# ⚠️ GIU DANH SACH NAY HEP BANG DUNG NHU CAU. Ban truoc co them `logs`, `events`,
# `top`, `port` "cho du" du script khong dung: `docker logs cliproxy` khong
# --tail se do ca log ung dung (co the chua token/prompt) vao log CI, con
# `docker events` khong --since se chay vo han va an het command_timeout. Cho
# phep mot dong tu khong dung toi = mo san mot cua cho nguoi sau.
DONG_TU_CHO_PHEP = {
    "version",
    "info",
    "ps",
    "stats",
    "inspect",       # bi siet rieng o bat bien 2b: bat buoc co --format
    "exec",          # bi siet rieng o bat bien 2
}

# Nhom lenh hai tang: `docker <nhom> <dong tu>`.
NHOM_HAI_TANG = {
    "network": {"ls", "inspect"},
    "volume": {"ls", "inspect"},
    "image": {"ls", "inspect", "history"},
    "container": {"ls", "inspect", "stats", "top", "port", "logs"},
    "system": {"df", "info"},
    "compose": {"version", "ls", "ps"},
    "node": {"ls", "inspect"},
    "service": {"ls", "inspect", "ps"},
    "stack": {"ls", "ps", "services"},
    "swarm": set(),          # moi dong tu swarm deu la ghi
    "builder": set(),
    "plugin": {"ls", "inspect"},
    "context": {"ls", "inspect", "show"},
    "config": {"ls", "inspect"},
    "secret": {"ls"},
}


def _tach_lenh_docker(script):
    """Tra ve danh sach (lenh_goc, nhom, dong_tu) cho moi lan goi docker.

    Cat lenh tai cac ky tu noi (`|`, `;`, `&&`, newline) de khong bo sot lenh
    thu hai trong mot chuoi. Bo qua moi flag (`-f x.yml`, `--context y`) truoc
    khi lay dong tu — day chinh la cho denylist cu bi thung.
    """
    ket_qua = []
    # `docker-compose` (v1, co gach noi) phai duoc tinh nhu `docker compose`.
    # `(?![\w.-])` loai `docker.sock`, `docker.io`, `dockerd` — chung la duong
    # dan/ten rieng, khong phai lenh.
    for m in re.finditer(r"\bdocker(-compose)?(?![\w.-])([^\n|;&]*)", script):
        la_compose_v1 = m.group(1) is not None
        phan_con_lai = m.group(2)
        tokens = phan_con_lai.split()

        # Bo flag va gia tri cua flag o dang `--key=value` / `-f file`.
        sach = []
        bo_qua_ke_tiep = False
        for t in tokens:
            # Chuyen huong (`2>`, `>`, `2>&1`) ket thuc phan doi so cua lenh.
            if t.startswith(">") or re.fullmatch(r"\d*>&?\d*", t):
                break
            if bo_qua_ke_tiep:
                bo_qua_ke_tiep = False
                continue
            if t.startswith("-"):
                # Flag nhan gia tri roi: `-f`, `-H`, `-p`, `--context`, `--format`
                if "=" not in t and t in {"-f", "-H", "-p", "--context", "--format", "--host", "--filter"}:
                    bo_qua_ke_tiep = True
                continue
            sach.append(t)

        if la_compose_v1:
            nhom, dong_tu = "compose", (sach[0] if sach else "")
        elif not sach:
            continue  # `docker` tran, vo hai
        elif sach[0] in NHOM_HAI_TANG:
            nhom, dong_tu = sach[0], (sach[1] if len(sach) > 1 else "")
        else:
            nhom, dong_tu = None, sach[0]

        ket_qua.append((m.group(0).strip(), nhom, dong_tu))
    return ket_qua


def test_moi_lenh_docker_deu_nam_trong_allowlist():
    vi_pham = []
    for goc, nhom, dong_tu in _tach_lenh_docker(ssh_script()):
        if nhom is None:
            if dong_tu not in DONG_TU_CHO_PHEP:
                vi_pham.append((goc, f"dong tu '{dong_tu}' khong trong allowlist"))
        else:
            if dong_tu not in NHOM_HAI_TANG[nhom]:
                vi_pham.append((goc, f"'{nhom} {dong_tu}' khong trong allowlist"))
    assert not vi_pham, (
        "Lenh docker KHONG phai chi-doc trong workflow khao sat:\n"
        + "\n".join(f"  {g}  -> {ly_do}" for g, ly_do in vi_pham)
        + "\nderper la relay chinh cua tailnet — khong duoc dung toi."
    )


# Cac chuoi PHAI bi chan. Khong co test nguoc nay thi khong biet rao chan con
# song hay da muc — denylist cu tung 'xanh' trong khi de lot `compose -f ... up`.
@pytest.mark.parametrize(
    "lenh_doc",
    [
        "docker compose -f /opt/x/docker-compose.yml up -d",
        "docker compose -p derp up -d --force-recreate",
        "docker-compose up -d",
        "docker --context default run --rm alpine",
        "docker -H unix:///var/run/docker.sock restart derper",
        "docker update --memory 512m cliproxy",
        "docker cp /tmp/x caddy-edge:/etc/caddy/Caddyfile",
        "docker network create edge",
        "docker volume rm derper_certs",
        "docker system prune -af",
        "docker swarm init",
        "docker service update --replicas 0 derper",
        "docker rename derper derper-old",
        "docker commit derper backup",
        "docker login -u x -p y",
        "docker ps && docker rm -f derper",
        "docker inspect derper | grep x; docker stop derper",
    ],
)
def test_allowlist_chan_duoc_lenh_ghi_that(lenh_doc):
    """Moi chuoi tren deu tung lot qua denylist cu, hoac la vector su co da xay ra."""
    bi_chan = False
    for _goc, nhom, dong_tu in _tach_lenh_docker(lenh_doc):
        if nhom is None:
            if dong_tu not in DONG_TU_CHO_PHEP:
                bi_chan = True
        elif dong_tu not in NHOM_HAI_TANG[nhom]:
            bi_chan = True
    assert bi_chan, f"Allowlist KHONG chan duoc lenh ghi: {lenh_doc!r}"


# ---------- bat bien 2: docker exec bi siet rieng ----------

# `docker exec <container> <lenh doc>` — cho phep dung mot so lenh doc cau hinh.
# `nginx -T` nam trong danh sach: do la cach DUY NHAT biet nginx dang nap cau
# hinh nao (bind mount doi ma khong recreate thi file tren dia khac voi cau hinh
# dang chay — su co that 2026-08-27).
#
# `timeout N` dung TRUOC `docker` (do la cach bash chay: timeout boc ca lenh).
# Ban truoc viet `docker exec (?:timeout \d+ )?...` — dat nhom sau `exec` — nen
# no la code chet: xoa `timeout 15` khoi script van xanh het.
EXEC_AN_TOAN = re.compile(
    r"timeout \d+ docker exec [A-Za-z0-9_.-]+ "
    r"(?:cat|ls|head|tail|nginx -T|caddy version)\b"
)


def test_moi_docker_exec_deu_la_lenh_doc_va_co_timeout():
    """Dem KHOP: moi lan xuat hien `docker exec` phai khop pattern an toan.

    Kieu cu dung `re.finditer` roi kiem tung ket qua — khi regex khong khop gi
    thi vong lap khong chay va KHONG co assert nao, nen
    `docker exec c /bin/sh -c 'echo x > /etc/caddy/Caddyfile'` lot sach.

    `timeout` la bat buoc: `docker exec edge-nginx nginx -T` tren mot container
    hap hoi se treo het command_timeout 3m, giu concurrency group
    'deploy-vpn4-host' va chan rollback khan cap cua derper.
    """
    script = ssh_script()
    tong = len(re.findall(r"docker exec\b", script))
    an_toan = len(EXEC_AN_TOAN.findall(script))
    assert tong == an_toan, (
        f"Co {tong} lan `docker exec` nhung chi {an_toan} lan khop pattern an "
        "toan. Moi lan exec phai la: timeout N docker exec <ten> "
        "<cat|ls|head|tail|nginx -T|caddy version>"
    )


def test_docker_inspect_phai_co_format_va_khong_doc_config():
    """`docker inspect <ten>` TRAN in toan bo JSON, GOM CA Config.Env.

    Do la noi chua CLIPROXY_API_KEY va OPENCODE_SERVER_PASSWORD. GitHub KHONG
    mask duoc gia tri no khong biet truoc -> secret di thang vao log CI cong
    khai. Chan bang chuoi `.Config.Env` la khong du: lenh tran khong he chua
    chuoi do. Phai bat buoc co --format va soi noi dung format.
    """
    script = ssh_script()
    for dong in script.splitlines():
        if "docker inspect" not in dong and "inspect " not in dong:
            continue
        if not re.search(r"\binspect\b", dong):
            continue
        # `docker network/volume inspect` cung phai co format.
        assert re.search(r"inspect\b[^|\n]*(?:-f|--format)\b", dong), (
            f"`inspect` khong co --format se in CA Config.Env (API key):\n  {dong.strip()}"
        )
        assert not re.search(r"\.Config\b(?!\.Image\b)", dong), (
            f"format doc .Config — vung chua bien moi truong:\n  {dong.strip()}"
        )


def test_docker_exec_khong_duoc_mo_shell():
    script = ssh_script()
    for dong in script.splitlines():
        if "docker exec" not in dong:
            continue
        for xau in (" sh ", " bash ", "/bin/sh", "/bin/bash", " -c ", "&&", ";"):
            assert xau not in dong, (
                f"docker exec mo shell / noi lenh ({xau!r}) — co the ghi de cau "
                f"hinh trong container:\n  {dong.strip()}"
            )


# ---------- bat bien 3: khong ghi file / khong sua host ----------

LENH_GHI_FILE = [
    r"\bsed\s+-i\b",
    r"\btee\b",
    r"\bcp\s",
    r"\bmv\s",
    r"\bdd\s+.*\bof=",
    r"\btruncate\b",
    r"\binstall\s+-",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bmkdir\b",
    r"\btouch\b",
    r"\brsync\b",
    r"\bln\s+-s",
    r"\brm\s+-",
]


def test_khong_co_lenh_ghi_file():
    script = ssh_script()
    vi_pham = [p for p in LENH_GHI_FILE if re.search(p, script)]
    assert not vi_pham, f"Workflow khao sat ghi file tren vpn4: {vi_pham}"


def test_khong_redirect_ra_file():
    """Bat ca duong dan TUONG DOI.

    Script co `cd "$DEPLOY_PATH"` o muc [10], nen moi redirect tuong doi sau do
    roi thang vao repo deploy. Regex cu chi bat duong dan tuyet doi.
    """
    script = ssh_script()

    # Xoa truoc cac redirect VO HAI, roi coi MOI `>` con lai la vi pham
    # (fail-closed). Cach cu — liet ke `>` roi loai tru tung truong hop — de lot
    # ba dang deu la ghi file that: `> "x"` (dich co ngoac), `2>err.log` va
    # `&>out` (bi lookbehind chan truoc khi kip xet).
    sach = re.sub(r"\d*>\s*&\s*\d", " ", script)          # 2>&1, >&2
    sach = re.sub(r"&?\d*>>?\s*/dev/null\b", " ", sach)   # >/dev/null, 2>/dev/null
    # Mui ten van ban trong chuoi echo: `-> caddy-edge:8444`, `--> derper`.
    # CHI xoa dung hai ky tu nay. Ban truoc con co `-\w+\s+\S*>\S*` de bo qua
    # "flag roi den >", nhung chinh no nuot ca `ls -1 > stolen.txt` -> bon dot
    # bien redirect deu lot.
    sach = re.sub(r"--?>", " ", sach)

    ghi = [m.group(0).strip() for m in re.finditer(r"&?\d*>>?\s*\S+", sach)]
    assert not ghi, (
        f"Workflow redirect ra file tren vpn4: {ghi}. Khao sat chi duoc doc; "
        "redirect tuong doi se roi vao repo deploy vi muc [10] co `cd $DEPLOY_PATH`."
    )


def test_khong_eval_va_khong_gan_lenh_vao_bien():
    """Dong ba duong nguy trang ma allowlist regex khong the chan.

    `D=docker; $D restart derper` — dong gan khop 'docker' voi phan du rong nen
    duoc bo qua, dong dung lai khong he co chu 'docker'. Tuong tu voi alias va
    `eval "$CMD"`. Chi phi dong lai gan bang 0 vi script khao sat khong can toi
    bat ky cau truc nao trong so nay.
    """
    script = ssh_script()
    assert not re.search(r"\beval\b", script), (
        "`eval` cho phep dung chuoi ghep de chay lenh ma allowlist khong nhin thay"
    )
    assert not re.search(r"\balias\b", script), "alias co the doi ten mot lenh ghi"
    gan = re.findall(r"\b\w+=[\"']?docker\b", script)
    assert not gan, (
        f"Gan lenh docker vao bien ({gan}): lenh thuc su se chay qua bien va "
        "khong con chu 'docker' de allowlist bat"
    )


def test_khong_sua_repo_tren_host():
    script = ssh_script()
    nguy_hiem = [r"git\s+reset", r"git\s+checkout", r"git\s+pull", r"git\s+fetch", r"git\s+clean"]
    vi_pham = [p for p in nguy_hiem if re.search(p, script)]
    assert not vi_pham, (
        f"Workflow khao sat sua repo tren vpn4: {vi_pham}. Chi duoc doc trang thai."
    )


def test_khong_sua_systemd_hay_firewall():
    script = ssh_script()
    nguy_hiem = [
        r"systemctl\s+(start|stop|restart|enable|disable|mask)",
        r"ufw\s+(allow|deny|delete|enable|disable|reset)",
        r"iptables\s+-[AIDFXZ]\b",
    ]
    vi_pham = [p for p in nguy_hiem if re.search(p, script)]
    assert not vi_pham, f"Workflow sua dich vu/firewall tren vpn4: {vi_pham}"


# ---------- bat bien 4+5: lich chay an toan ----------

def test_dung_chung_concurrency_group_voi_deploy_vpn4():
    wf = load()
    group = wf.get("concurrency", {}).get("group")
    assert group == "deploy-vpn4-host", (
        f"concurrency group la '{group}', phai la 'deploy-vpn4-host' de khong "
        "khao sat chen ngang deploy-derp-vpn4 / deploy-cliproxy / deploy-edge-vpn4"
    )
    assert wf["concurrency"].get("cancel-in-progress") is False, (
        "cancel-in-progress phai la false — khong duoc huy deploy dang chay"
    )


def test_command_timeout_ngan():
    """Group nay dung chung voi deploy. Phien treo lau se chan rollback khan cap."""
    to = str(ssh_step()["with"].get("command_timeout", ""))
    m = re.fullmatch(r"(\d+)m", to)
    assert m and int(m.group(1)) <= 5, (
        f"command_timeout='{to}'. Khao sat chay <90s; de qua 5m thi mot phien treo "
        "se giu concurrency group 'deploy-vpn4-host' va chan deploy rollback derper."
    )


def test_chi_chay_bang_tay():
    # PyYAML doc `on:` thanh True (YAML 1.1). Chap nhan ca hai dang khoa.
    wf = load()
    trigger = wf.get("on", wf.get(True))
    assert set(trigger) == {"workflow_dispatch"}, (
        f"Workflow khao sat phai CHI chay bang tay, dang co trigger: {list(trigger)}"
    )


# ---------- bat bien 6: secret ----------

def test_ssh_dung_secret_cua_vpn4():
    host = ssh_step()["with"]["host"]
    assert "SSH_HOST_VPN4" in host, (
        f"SSH tro toi '{host}' — khao sat nay danh cho vpn4, dung nham secret "
        "la SSH vao may khac"
    )


def test_secret_khong_interpolate_vao_run_hay_script():
    """Secret phai di qua `env:`/`with:`, khong thay the van ban thang vao shell.

    Vua la chong script-injection, vua dong bo voi deploy-edge-vpn4.yml.
    """
    wf = load()
    vi_pham = []
    for step in wf["jobs"]["survey"]["steps"]:
        for khoa in ("run",):
            noi_dung = step.get(khoa)
            if noi_dung and "${{ secrets." in noi_dung:
                vi_pham.append(f"{step.get('name')}.{khoa}")
        script = step.get("with", {}).get("script")
        if script and "${{ secrets." in script:
            vi_pham.append(f"{step.get('name')}.with.script")
    assert not vi_pham, (
        f"Secret interpolate thang vao shell tai: {vi_pham}. Dua qua `env:` roi "
        "dung bien shell, nhu deploy-edge-vpn4.yml."
    )


def test_khong_bat_trace_va_khong_doc_bien_moi_truong_container():
    """Ba duong ro ri secret thuc te, thay cho test cu gan nhu khong kiem gi."""
    script = ssh_script()
    assert not re.search(r"\bset\s+-[a-z]*x", script), (
        "`set -x` in moi lenh ra log, keo theo ca gia tri bien nhay cam"
    )
    assert not re.search(r"\bbash\s+-x\b", script), "bash -x in moi lenh ra log"
    assert "docker compose config" not in script, (
        "`docker compose config` in TOAN BO bien moi truong da giai, gom "
        "CLIPROXY_API_KEY"
    )
    assert not re.search(r"\.Config\.Env|json \.Config\b", script), (
        "doc .Config.Env la doc thang bien moi truong cua container "
        "(CLIPROXY_API_KEY / OPENCODE_SERVER_PASSWORD)"
    )


def test_khong_echo_bien_la_secret():
    """DEPLOY_PATH la secret: echo ra se bi mask thanh *** lam muc do vo nghia."""
    script = ssh_script()
    assert not re.search(r'echo\s+"[^"]*\$DEPLOY_PATH', script), (
        "echo $DEPLOY_PATH: GitHub mask secret thanh *** -> muc [10] mat gia tri. "
        "In TRANG THAI (ton tai/thieu) thay vi gia tri."
    )


def test_ss_khong_in_ten_tien_trinh():
    """`ss -p` bien log thanh ban kiem ke dich vu. Khao sat chi can biet cong."""
    script = ssh_script()
    assert not re.search(r"\bss\s+-\w*p\w*\b", script), (
        "Bo co -p cua ss: khao sat chi can biet cong trong hay khong, in ten "
        "tien trinh lam log thanh tai lieu trinh sat"
    )


# ---------- bat bien 7: cac bay van hanh da biet ----------

def test_khong_duoc_them_script_stop():
    """script_stop chen kiem exit code sau MOI dong -> cam `else`, cam heredoc.

    Script khao sat dung `else` o nhieu cho de bao "KHONG XAC DINH" thay vi im
    lang. Them script_stop vao se lam vo toan bo cac nhanh do (bay nay da duoc
    ghi nhan trong test/test_edge_vpn4.py cho deploy-edge-vpn4).
    """
    assert ssh_step()["with"].get("script_stop") in (None, False), (
        "KHONG duoc bat script_stop cho workflow khao sat: no cam cu phap `else`, "
        "ma script nay dua vao `else` de bao trang thai KHONG XAC DINH"
    )


def test_docker_stats_phai_co_no_stream():
    """Thieu --no-stream thi docker stats chay vo han -> het command_timeout ->
    giu concurrency group 'deploy-vpn4-host' -> chan rollback khan cap."""
    for dong in ssh_script().splitlines():
        if "docker stats" in dong:
            assert "--no-stream" in dong, (
                f"`docker stats` thieu --no-stream, se chay vo han:\n  {dong.strip()}"
            )
            assert re.search(r"timeout \d+ docker stats", dong), (
                f"`docker stats` nen boc `timeout N`:\n  {dong.strip()}"
            )


def test_bao_truoc_khi_ket_luan_cong_trong():
    """Loi nguy hiem nhat cua khao sat la bao SAI mot cach im lang.

    `ss` that bai -> output rong -> `grep -q` khong khop -> in "trong" -> ta
    thiet ke stack dam vao mot cong dang dung.
    """
    script = ssh_script()
    assert "KHONG XAC DINH" in script, (
        "Script phai phan biet 'khong co gi' voi 'khong hoi duoc' — neu khong, "
        "lenh that bai se bi doc nham thanh ket qua rong hop le"
    )
    assert re.search(r"sudo -n", script), (
        "Dung `sudo -n`: phien SSH khong co TTY, sudo thieu NOPASSWD phai that "
        "bai ngay thay vi treo"
    )
    assert "::error::sudo" in script, (
        "Phai bao ::error:: khi sudo hong — moi so lieu sau do deu khong tin cay"
    )


# ---------- noi dung khao sat phai du de thiet ke stack ----------

CAU_HOI_BAT_BUOC = {
    "RAM con lai": r"free -h",
    "dung luong dia": r"df -h",
    "thu muc du lieu docker that": r"DockerRootDir",
    "che do swarm": r"Swarm\.LocalNodeState",
    "docker rootless?": r"SecurityOptions",
    "quyen docker.sock": r"/var/run/docker\.sock",
    "cong dang nghe": r"ss -tln",
    "cong 9443 co trong khong": r"9443",
    "mang docker": r"docker network ls",
    "container dang chay": r"docker ps",
    "mem_limit da cam ket": r"HostConfig\.Memory",
    "cau hinh nginx DANG NAP": r"nginx -T",
    "trang thai container edge": r"State\.Status",
    # Chain quyet dinh voi container publish cong. Doc INPUT la nhin nham cho:
    # jail opencode-401 phai dat `chain = DOCKER-USER` chinh vi ly do nay.
    "firewall chain DOCKER-USER": r"DOCKER-USER",
}


def test_khao_sat_tra_loi_du_cau_hoi_thiet_ke():
    script = ssh_script()
    thieu = [ten for ten, pat in CAU_HOI_BAT_BUOC.items() if not re.search(pat, script)]
    assert not thieu, f"Khao sat thieu du lieu de thiet ke stack Portainer: {thieu}"


def test_khong_dung_pipe_nuot_loi_khi_can_bao_khong_xac_dinh():
    """`lenh | head -N || echo "KHONG XAC DINH"` la bay im lang.

    Exit code cua pipeline la cua lenh CUOI (`head`), luon 0, nen `|| echo`
    khong bao gio chay. Lenh that bai chi in khoang trang va ta doc nham thanh
    "khong co gi". Phai gan vao bien roi kiem tra rong.
    """
    xau = []
    for dong in ssh_script().splitlines():
        if re.search(r"\|\s*head\b[^|]*\|\|", dong):
            xau.append(dong.strip())
    assert not xau, (
        "Pipe nuot exit code — `|| echo` sau `| head` khong bao gio chay:\n  "
        + "\n  ".join(xau)
    )


def test_bao_do_khi_sudo_hong():
    """`::error::` chi la annotation, KHONG lam check do.

    Khong co `exit 1` thi job van hien dau xanh du moi so lieu deu rac, va
    nguoi doc luot qua dau xanh roi thiet ke stack tren du lieu khong tin cay.
    """
    script = ssh_script()
    assert re.search(r"SUDO_OK\"? != \"?1", script), "Phai co nhanh kiem tra SUDO_OK"
    assert "exit 1" in script, (
        "Thieu `exit 1` khi sudo hong: job se xanh du khao sat that bai hoan toan"
    )
