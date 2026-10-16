#!/usr/bin/env python3
"""Mutation test cho rao chan read-only cua workflow khao sat vpn4.

VI SAO CAN FILE NAY: test xanh KHONG chung minh rao chan con song.

Ban dau test/test_survey_vpn4.py dung DENYLIST regex va xanh 11/11 — trong khi
`docker compose -f x.yml up -d` (cach viet pho bien nhat trong repo nay) lot
qua sach, vi `up` khong con dung ngay sau `compose`. Mot lenh nhu the chay tren
vpn4 la recreate derper, tuc ca tailnet mat relay. Test xanh luc do la NIEM TIN
SAI, nguy hiem hon la khong co test.

File nay nhet tung lenh nguy hiem vao mot BAN SAO cua workflow roi doi hoi
pytest phai DO — va phai do DUNG CAI TEST duoc chi dinh.

⚠️ VI SAO PHAI KIEM DUNG TEN TEST, khong chi kiem "co do hay khong": nhieu dot
bien vo tinh lam do MOT TEST KHAC. Vi du dot bien doi `.HostConfig.Memory` ->
`.Config.Env` cung xoa luon mot muc trong CAU_HOI_BAT_BUOC, nen
`test_khao_sat_tra_loi_du_cau_hoi_thiet_ke` do — bat ke rao chan chong ro ri
secret con song hay da bi vo hieu hoa. Doc moi returncode thi con so "chan duoc
N/N" cao hon muc thuc su duoc chung minh. Day dung la loai NIEM TIN SAI ma file
nay sinh ra de diet, nen no khong duoc phep mac chinh loi do.

Khong sua file goc; moi thu dien ra trong thu muc tam.

Chay: python3 test/mutation_survey_vpn4.py
"""
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

SRC = pathlib.Path(__file__).resolve().parent.parent
WF_REL = ".github/workflows/survey-docker-vpn4.yml"
TEST_REL = "test/test_survey_vpn4.py"

# Neo dung chung cho cac dot bien "them mot lenh moi vao script".
# CO Y chon mot dong KHONG nam trong CAU_HOI_BAT_BUOC: neo vao `docker network
# ls` hay `.HostConfig.Memory` se xoa mat mot cau hoi bat buoc va lam do nham
# test_khao_sat_tra_loi_du_cau_hoi_thiet_ke.
NEO_TRUNG_TINH = "            echo \"--- CPU ---\""

# (mo ta, chuoi can thay, chuoi thay the, ten test PHAI do)
DOT_BIEN = [
    ("docker compose -f ... up -d  (cach viet pho bien nhat trong repo)",
     NEO_TRUNG_TINH,
     '            $SUDO docker compose -f /opt/x/docker-compose.yml up -d',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker-compose up -d  (v1, gach noi)",
     NEO_TRUNG_TINH,
     '            $SUDO docker-compose up -d',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker update --memory  (tai tao su co OOM-kill cliproxy 2026-08-02)",
     NEO_TRUNG_TINH,
     '            $SUDO docker update --memory 512m cliproxy',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker restart derper  (mat relay ca tailnet)",
     NEO_TRUNG_TINH,
     '            $SUDO docker restart derper',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker -H unix://... restart  (flag chen giua)",
     NEO_TRUNG_TINH,
     '            $SUDO docker -H unix:///var/run/docker.sock restart derper',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker network create  (dung toi mang edge dang chay)",
     NEO_TRUNG_TINH,
     '            $SUDO docker network create portainer-net',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker system prune  (xoa volume/image dang dung)",
     NEO_TRUNG_TINH,
     '            $SUDO docker system prune -af',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker swarm init  (bien host thanh swarm manager)",
     NEO_TRUNG_TINH,
     '            $SUDO docker swarm init',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker cp ghi de file trong container",
     NEO_TRUNG_TINH,
     '            $SUDO docker cp /tmp/x caddy-edge:/etc/caddy/Caddyfile',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),

    ("docker exec mo shell ghi de Caddyfile",
     '$SUDO timeout 15 docker exec caddy-edge cat /etc/caddy/Caddyfile',
     '$SUDO docker exec caddy-edge /bin/sh -c "echo x > /etc/caddy/Caddyfile"',
     "test_docker_exec_khong_duoc_mo_shell"),
    ("docker exec noi lenh bang &&",
     '$SUDO timeout 15 docker exec caddy-edge cat /etc/caddy/Caddyfile',
     '$SUDO timeout 15 docker exec caddy-edge cat /etc/caddy/Caddyfile && docker rm -f derper',
     "test_docker_exec_khong_duoc_mo_shell"),
    ("xoa `timeout` truoc docker exec  (nginx -T treo het command_timeout)",
     '$SUDO timeout 15 docker exec edge-nginx nginx -T',
     '$SUDO docker exec edge-nginx nginx -T',
     "test_moi_docker_exec_deu_la_lenh_doc_va_co_timeout"),

    ("docker inspect KHONG --format  (in ca Config.Env -> lo CLIPROXY_API_KEY)",
     "$SUDO docker inspect -f '{{.HostConfig.Memory}}' \"$c\"",
     '$SUDO docker inspect "$c"',
     "test_docker_inspect_phai_co_format_va_khong_doc_config"),
    ("format doc .Config.Env truc tiep",
     "-f '{{.HostConfig.Memory}}'",
     "-f '{{.Config.Env}}'",
     "test_docker_inspect_phai_co_format_va_khong_doc_config"),
    ("docker logs  (do log ung dung, co the chua token, vao log CI)",
     NEO_TRUNG_TINH,
     '            $SUDO docker logs cliproxy',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker compose config  (in toan bo bien moi truong)",
     NEO_TRUNG_TINH,
     '            $SUDO docker compose config',
     "test_khong_bat_trace_va_khong_doc_bien_moi_truong_container"),

    ("sed -i sua config tren host",
     NEO_TRUNG_TINH,
     '            sed -i s/a/b/ /etc/hosts',
     "test_khong_co_lenh_ghi_file"),
    ("redirect TUONG DOI vao repo deploy (sau `cd $DEPLOY_PATH`)",
     NEO_TRUNG_TINH,
     '            ls -1 > stolen.txt',
     "test_khong_redirect_ra_file"),
    ("redirect co NGOAC KEP  (ban truoc bo qua vi dich ket thuc bang \")",
     NEO_TRUNG_TINH,
     '            ls -1 > "stolen.txt"',
     "test_khong_redirect_ra_file"),
    ("redirect co SO FD `2>err.log`  (ban truoc bi lookbehind chan, khong xet)",
     NEO_TRUNG_TINH,
     '            ls -1 2>err.log',
     "test_khong_redirect_ra_file"),
    ("redirect `&>out`  (ban truoc bi lookbehind chan)",
     NEO_TRUNG_TINH,
     '            ls -1 &>out',
     "test_khong_redirect_ra_file"),

    ("bo --no-stream khoi docker stats  (treo het command_timeout)",
     'timeout 30 docker stats --no-stream',
     'timeout 30 docker stats',
     "test_docker_stats_phai_co_no_stream"),
    ("them script_stop: true  (pha moi nhanh else)",
     '          command_timeout: 3m',
     '          script_stop: true\n          command_timeout: 3m',
     "test_khong_duoc_them_script_stop"),
    ("command_timeout 10m  (chan rollback khan cap cua derper)",
     '          command_timeout: 3m',
     '          command_timeout: 10m',
     "test_command_timeout_ngan"),

    ("set -x  (in moi lenh + bien ra log)",
     NEO_TRUNG_TINH,
     '            set -x',
     "test_khong_bat_trace_va_khong_doc_bien_moi_truong_container"),
    ("ss -tlnp  (in ten tien trinh -> log thanh ban do tan cong)",
     'ss -tln 2>/dev/null',
     'ss -tlnp 2>/dev/null',
     "test_ss_khong_in_ten_tien_trinh"),
    ("echo $DEPLOY_PATH  (secret bi mask -> muc [10] vo nghia)",
     '              echo "DEPLOY_PATH: ton tai"',
     '              echo "DEPLOY_PATH: $DEPLOY_PATH"',
     "test_khong_echo_bien_la_secret"),
    ("secret interpolate thang vao run:  (script injection)",
     '          HOST_EXPECT: ${{ secrets.SSH_HOST_VPN4 }}\n        run: |',
     '        run: |\n          HOST_EXPECT="${{ secrets.SSH_HOST_VPN4 }}"',
     "test_secret_khong_interpolate_vao_run_hay_script"),

    ("them trigger push  (tu dong SSH vao production moi lan commit)",
     'on:\n  workflow_dispatch:',
     'on:\n  push:\n  workflow_dispatch:',
     "test_chi_chay_bang_tay"),
    ("doi sang secrets.SSH_HOST  (SSH nham may khac)",
     'host: ${{ secrets.SSH_HOST_VPN4 }}',
     'host: ${{ secrets.SSH_HOST }}',
     "test_ssh_dung_secret_cua_vpn4"),
    ("doi concurrency group  (khao sat chen ngang deploy)",
     'group: deploy-vpn4-host',
     'group: survey-only',
     "test_dung_chung_concurrency_group_voi_deploy_vpn4"),
    ("cancel-in-progress: true  (huy deploy dang chay)",
     'cancel-in-progress: false',
     'cancel-in-progress: true',
     "test_dung_chung_concurrency_group_voi_deploy_vpn4"),

    ("systemctl restart docker  (giet moi container tren host)",
     NEO_TRUNG_TINH,
     '            systemctl restart docker',
     "test_khong_sua_systemd_hay_firewall"),
    ("iptables -A  (them luat tuong lua)",
     NEO_TRUNG_TINH,
     '            iptables -A INPUT -p tcp --dport 9443 -j ACCEPT',
     "test_khong_sua_systemd_hay_firewall"),
    ("git reset --hard  (xoa thay doi tren repo deploy)",
     NEO_TRUNG_TINH,
     '            git reset --hard origin/main',
     "test_khong_sua_repo_tren_host"),
    ("bo sudo -n  (sudo hong -> bao nham moi cong deu trong)",
     'SUDO="sudo -n"',
     'SUDO="sudo"',
     "test_bao_truoc_khi_ket_luan_cong_trong"),

    # --- Dot bien dong cac lo DA DUOC CHUNG MINH la thung o review vong 2 ---
    ("lenh giau sau `#` trong CHUOI  (# trong ngoac kep la van ban, `;` van chay)",
     NEO_TRUNG_TINH,
     '            echo "ghi chu # "; docker restart derper',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("them step ssh-action THU HAI  (ban truoc chi quet step dau tien)",
     '      - name: Kiem tra DNS cho domain Portainer du kien',
     '''      - name: Khao sat them
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.SSH_HOST_VPN4 }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_KEY }}
          script: |
            docker restart derper

      - name: Kiem tra DNS cho domain Portainer du kien''',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("gan docker vao bien roi goi qua bien  (nguy trang khoi allowlist)",
     NEO_TRUNG_TINH,
     '            D=docker; $D restart derper',
     "test_khong_eval_va_khong_gan_lenh_vao_bien"),
    ("eval chuoi ghep  (allowlist khong nhin thay lenh that)",
     NEO_TRUNG_TINH,
     '            eval "$CMD"',
     "test_khong_eval_va_khong_gan_lenh_vao_bien"),
    ("pipe nuot exit code  (`| head` lam `|| echo` khong bao gio chay)",
     '              echo "$UDP_LISTEN" | head -40',
     '              $SUDO ss -uln 2>/dev/null | head -40 || echo "KHONG XAC DINH"',
     "test_khong_dung_pipe_nuot_loi_khi_can_bao_khong_xac_dinh"),
    ("bo `exit 1` khi sudo hong  (job xanh du moi so lieu la rac)",
     '              exit 1',
     '              :',
     "test_bao_do_khi_sudo_hong"),
    ("chi doc chain INPUT  (bo DOCKER-USER — chain that su chi phoi container)",
     'for chain in DOCKER-USER FORWARD INPUT; do',
     'for chain in INPUT; do',
     "test_khao_sat_tra_loi_du_cau_hoi_thiet_ke"),

    # --- Dot bien dong cac lo phat hien o review vong 3 ---
    # `docker container X` la dang DAY DU cua `docker X`. Go mot dong tu khoi
    # DONG_TU_CHO_PHEP ma de lai trong NHOM_HAI_TANG["container"] la khong go gi.
    ("docker container logs  (dang day du cua `docker logs` — di vong allowlist)",
     NEO_TRUNG_TINH,
     '            $SUDO docker container logs cliproxy',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker container top  (cung duong vong)",
     NEO_TRUNG_TINH,
     '            $SUDO docker container top derper',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker image history  (in CREATED BY tung layer — lo ARG/ENV luc build)",
     NEO_TRUNG_TINH,
     '            $SUDO docker image history cliproxy',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
    ("docker container stats KHONG --no-stream  (test cu tim chuoi 'docker stats')",
     'timeout 30 docker stats --no-stream',
     'timeout 30 docker container stats',
     "test_docker_stats_phai_co_no_stream"),

    # Rao chan chi ap len step co `uses` chua 'ssh-action'. Dung action khac de
    # chay lenh tu xa la vo hinh voi toan bo test.
    ("them step appleboy/scp-action  (GHI FILE thang len vpn4, khong qua rao chan)",
     '      - name: Kiem tra DNS cho domain Portainer du kien',
     '''      - name: Day file len
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ secrets.SSH_HOST_VPN4 }}
          source: x
          target: /opt

      - name: Kiem tra DNS cho domain Portainer du kien''',
     "test_chi_dung_action_trong_allowlist"),
    ("doi sang action SSH khac  (garygrossgarten/github-action-ssh)",
     'uses: appleboy/ssh-action@v1.2.0',
     'uses: garygrossgarten/github-action-ssh@v0.7.0',
     "test_chi_dung_action_trong_allowlist"),

    # test_secret_khong_interpolate... tung hard-code jobs["survey"] -> job thu
    # hai vo hinh.
    ("them JOB thu hai interpolate secret vao run:  (job khac 'survey')",
     'jobs:\n  survey:',
     '''jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - name: Kiem tra
        run: ssh -i ${{ secrets.SSH_KEY }} host

  survey:''',
     "test_secret_khong_interpolate_vao_run_hay_script"),

    # Parser phai bo qua `docker` trong DUONG DAN (/var/lib/docker/volumes) de
    # khong bao dong gia — nhung viec noi do KHONG duoc mo duong goi binary qua
    # duong dan tuyet doi.
    ("goi docker qua duong dan tuyet doi  (sau khi noi regex cho /var/lib/docker)",
     NEO_TRUNG_TINH,
     '            /usr/bin/docker restart derper',
     "test_moi_lenh_docker_deu_nam_trong_allowlist"),
]


def chay_test(thu_muc):
    """Chay pytest bang CHINH interpreter dang chay file nay.

    CI goi qua venv (`/tmp/venv-survey/bin/python test/mutation_...py`), may
    local co the goi bang uv. Dung sys.executable thi ca hai deu dung dung moi
    truong da co pytest + pyyaml, khong can biet truoc duong dan.

    Tra ve (returncode, tap ten test DA DO).
    """
    kq = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rf", TEST_REL],
        cwd=thu_muc, capture_output=True, text=True,
    )
    ra = kq.stdout + kq.stderr
    # Dong tom tat cua pytest: "FAILED test/x.py::ten_test - AssertionError..."
    da_do = set(re.findall(r"FAILED \S+::(\w+)", ra))
    return kq.returncode, da_do


def main():
    goc_wf = (SRC / WF_REL).read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / ".github/workflows").mkdir(parents=True)
        (tmp / "test").mkdir(parents=True)
        shutil.copy(SRC / TEST_REL, tmp / TEST_REL)

        # Chung minh ban GOC xanh truoc da. Khong co buoc nay thi mot file test
        # hong san se lam MOI dot bien "do" va bao cao 100% gia.
        (tmp / WF_REL).write_text(goc_wf, encoding="utf-8")
        rc, _ = chay_test(tmp)
        print(f"[co so] ban goc: {'PASS' if rc == 0 else 'FAIL'}")
        if rc != 0:
            print("Ban goc da FAIL — dung mutation test.")
            return 1
        print()

        hong = []
        for mo_ta, cu, moi, test_mong_doi in DOT_BIEN:
            if cu not in goc_wf:
                # Neo hong = fail-closed. Dot bien khong con kiem gi nhung van
                # bao "chan duoc" thi la bao cao gia.
                print(f"  NEO HONG    | {mo_ta}")
                hong.append(f"{mo_ta} [neo khong con trong file]")
                continue

            (tmp / WF_REL).write_text(goc_wf.replace(cu, moi, 1), encoding="utf-8")
            rc, da_do = chay_test(tmp)

            if rc == 0:
                print(f"  !!! LOT !!! | {mo_ta}")
                hong.append(f"{mo_ta} [khong test nao do]")
            elif test_mong_doi not in da_do:
                # Do, nhung do NHAM test khac -> rao chan nham toi chua chac song.
                print(f"  DO NHAM     | {mo_ta}")
                print(f"              | mong doi {test_mong_doi}, thuc te do: {sorted(da_do)}")
                hong.append(f"{mo_ta} [do nham test khac]")
            else:
                print(f"  CHAN DUOC   | {mo_ta}")

        print()
        print(f"Tong: {len(DOT_BIEN)} dot bien, chan dung {len(DOT_BIEN) - len(hong)}, co van de {len(hong)}")
        if hong:
            print("\nCAC DOT BIEN CO VAN DE:")
            for x in hong:
                print(f"  - {x}")
            return 1
        print("Moi dot bien deu bi chan boi DUNG test duoc chi dinh.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
