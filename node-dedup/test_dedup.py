"""Unit test cho logic dedup + collector (chay trong CI truoc khi deploy)."""
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

import json

from dedup import (aggregate_latency, init_db, init_latency_db,
                   is_allowed_report_src, is_tailnet_ip,
                   latency_series, normalize, parse_pingresult,
                   peer_relay_from_status, pingable_nodes, plan_actions,
                   probe_derp_region, query_all_server_pings, query_current_relay,
                   query_devices, query_latest_netcheck, record_netcheck, record_report,
                   render_derp_html, render_stats_html,
                   server_ping_all, validate_report, _parse_derp_regions)


def mk(id, host, given, user="u", online=False, last=0, ips=None):
    return {"id": id, "hostname": host, "given_name": given,
            "user": user, "online": online, "last_seen": last,
            "ips": ips or [], "machine_key": ""}


def test_keep_online_delete_offline_rename_clean():
    # 3 node itop: 8/11 offline, 15 online -> giu 15, xoa 8+11, doi ten 15 ve 'itop'
    nodes = [
        mk("8", "itop", "itop", online=False, last=100),
        mk("11", "itop", "itop-eu4igccy", online=False, last=200),
        mk("15", "itop", "itop-i8shta5a", online=True, last=300),
    ]
    acts = plan_actions(nodes)
    assert {a["id"] for a in acts if a["action"] == "delete"} == {"8", "11"}
    ren = [a for a in acts if a["action"] == "rename"]
    assert len(ren) == 1 and ren[0]["id"] == "15" and ren[0]["to"] == "itop"


def test_single_suffixed_node_renamed():
    nodes = [mk("15", "itop", "itop-i8shta5a", online=True, last=300)]
    acts = plan_actions(nodes)
    assert any(a["action"] == "rename" and a["to"] == "itop" for a in acts)
    assert not any(a["action"] == "delete" for a in acts)


def test_clean_single_node_no_action():
    nodes = [mk("6", "votam-pc", "votam-pc", online=True, last=300)]
    assert plan_actions(nodes) == []


def test_never_delete_online_duplicate():
    nodes = [mk("a", "h", "h", online=True, last=100),
             mk("b", "h", "h-x", online=True, last=200)]
    acts = plan_actions(nodes)
    assert any(a["action"] == "skip" and a["id"] == "a" for a in acts)
    assert not any(a["action"] == "delete" for a in acts)


def test_different_users_not_merged():
    nodes = [mk("1", "h", "h", user="x", online=True, last=1),
             mk("2", "h", "h-y", user="y", online=True, last=2)]
    assert not any(a["action"] == "delete" for a in plan_actions(nodes))


def test_offline_only_group_keeps_latest():
    # khong co node online -> giu cai last_seen moi nhat
    nodes = [mk("1", "h", "h-a", online=False, last=100),
             mk("2", "h", "h-b", online=False, last=500)]
    acts = plan_actions(nodes)
    assert {a["id"] for a in acts if a["action"] == "delete"} == {"1"}
    assert any(a["action"] == "rename" and a["id"] == "2" and a["to"] == "h" for a in acts)


def test_normalize_camel_and_snake():
    raw = [
        {"id": 6, "name": "votam-pc", "givenName": "votam-pc",
         "user": {"name": "votam"}, "online": True,
         "lastSeen": {"seconds": 123}, "ipAddresses": ["100.64.0.3", "fd7a::3"],
         "machineKey": "mkey:x"},
        {"id": 8, "name": "itop", "given_name": "itop-x",
         "user": {"name": "u"}, "online": False,
         "last_seen": {"seconds": 99}, "ip_addresses": ["100.64.0.1"],
         "machine_key": "mkey:y"},
    ]
    out = normalize(raw)
    assert out[0]["id"] == "6" and out[0]["hostname"] == "votam-pc"
    assert out[0]["given_name"] == "votam-pc" and out[0]["user"] == "votam"
    assert out[0]["online"] is True and out[0]["last_seen"] == 123
    assert out[1]["given_name"] == "itop-x" and out[1]["last_seen"] == 99


# ---------------- server ping: CHI giam sat node SONG ----------------

def test_pingable_nodes_chi_online():
    # Chi node ONLINE co IPv4 (khac 'collector') moi duoc ping. Offline / khong
    # ipv4 / chinh la collector -> bo qua.
    nodes = [
        mk("1", "alive", "alive", online=True, ips=["100.64.0.2", "fd7a::2"]),
        mk("2", "dead", "dead", online=False, ips=["100.64.0.3"]),      # offline -> bo
        mk("3", "collector", "collector", online=True, ips=["100.64.0.1"]),  # nguon -> bo
        mk("4", "noip", "noip", online=True, ips=["fd7a::9"]),          # khong co ipv4 -> bo
    ]
    assert pingable_nodes(nodes) == [("alive", "100.64.0.2")]


def test_server_ping_all_khong_ping_node_chet():
    # ping_fn gia: ghi lai IP da ping -> chung minh node offline KHONG bi ping
    # (vong poll khong ton ~8s/node chet cho timeout).
    pinged = []

    def fake_ping(ip):
        pinged.append(ip)
        return {"LatencySeconds": 0.01, "Endpoint": "1.2.3.4:41641"}

    nodes = [
        mk("1", "alive", "alive", online=True, ips=["100.64.0.2"]),
        mk("2", "dead", "dead", online=False, ips=["100.64.0.3"]),
    ]
    samples = server_ping_all(nodes, ping_fn=fake_ping)
    assert pinged == ["100.64.0.2"]                       # KHONG ping node offline
    assert len(samples) == 1
    assert samples[0]["dst"] == "alive" and samples[0]["ok"] is True


# ---------------- collector (MAC + latency) ----------------

def test_validate_report_ok():
    r = validate_report({
        "hostname": "itop", "ipv4": "100.64.0.1", "mac": "AA:BB:CC:DD:EE:FF",
        "samples": [{"dst": "votam", "dst_ip": "100.64.0.3",
                     "rtt_ms": 8.2, "path": "direct", "ok": True}],
    })
    assert r["hostname"] == "itop" and r["mac"] == "AA:BB:CC:DD:EE:FF"
    assert len(r["samples"]) == 1
    assert r["samples"][0]["dst"] == "votam" and r["samples"][0]["rtt_ms"] == 8.2


def test_validate_report_missing_hostname():
    with pytest.raises(ValueError):
        validate_report({"samples": []})


def test_validate_report_single_sample_as_dict():
    # PowerShell 5.1 gui 1 sample duoi dang object (khong phai list) -> van nhan.
    r = validate_report({"hostname": "itop",
                         "samples": {"dst": "votam", "rtt_ms": 9.0, "path": "direct", "ok": True}})
    assert len(r["samples"]) == 1 and r["samples"][0]["dst"] == "votam"


def test_validate_report_drops_bad_samples_and_defaults_ok():
    r = validate_report({"hostname": "h", "samples": [
        {"dst": "", "rtt_ms": 1},          # bo: thieu dst
        "notadict",                          # bo: khong phai dict
        {"dst": "p", "rtt_ms": None},        # giu: ok mac dinh False (rtt None)
        {"dst": "q", "rtt_ms": "5.5"},       # rtt chuoi -> 5.5, ok mac dinh True
    ]})
    dsts = {s["dst"]: s for s in r["samples"]}
    assert set(dsts) == {"p", "q"}
    assert dsts["p"]["ok"] is False and dsts["p"]["rtt_ms"] is None
    assert dsts["q"]["rtt_ms"] == 5.5 and dsts["q"]["ok"] is True


def test_aggregate_latency():
    rows = [
        {"src": "itop", "dst": "votam", "dst_ip": "x", "rtt_ms": 10.0, "path": "direct", "ok": True, "ts": 1},
        {"src": "itop", "dst": "votam", "dst_ip": "x", "rtt_ms": 20.0, "path": "derp:myderp", "ok": True, "ts": 2},
        {"src": "itop", "dst": "votam", "dst_ip": "x", "rtt_ms": None, "path": "", "ok": False, "ts": 3},
    ]
    agg = aggregate_latency(rows)
    assert len(agg) == 1
    a = agg[0]
    assert a["count"] == 3 and a["min_ms"] == 10.0 and a["max_ms"] == 20.0 and a["avg_ms"] == 15.0
    assert a["ok_pct"] == round(100 * 2 / 3, 1)
    assert a["direct_pct"] == round(100 * 1 / 3, 1)
    assert a["last_ts"] == 3 and a["last_path"] == ""


def _mem_db():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    init_latency_db(conn)
    return conn


def test_record_report_updates_mac_by_ipv4_and_inserts_samples():
    conn = _mem_db()
    conn.execute("INSERT INTO devices(user,hostname,mac,node_id,ipv4,machine_key,first_seen,last_seen,seen_count)"
                 " VALUES('u','itop',NULL,'1','100.64.0.1','mk',0,0,1)")
    conn.commit()
    rep = validate_report({"hostname": "itop", "ipv4": "100.64.0.1", "mac": "AA:BB:CC",
                           "samples": [{"dst": "votam", "dst_ip": "100.64.0.3",
                                        "rtt_ms": 8.0, "path": "direct", "ok": True}]})
    assert record_report(conn, rep, 123) == 1
    assert conn.execute("SELECT mac FROM devices WHERE hostname='itop'").fetchone()[0] == "AA:BB:CC"
    assert conn.execute("SELECT COUNT(*) FROM node_latency").fetchone()[0] == 1


def test_parse_pingresult():
    # SERVER ping qua LocalAPI -> PingResult
    d = parse_pingresult({"LatencySeconds": 0.012, "Endpoint": "1.2.3.4:41641"})
    assert d == {"ok": True, "rtt_ms": 12.0, "path": "direct"}
    r = parse_pingresult({"LatencySeconds": 0.045, "DERPRegionCode": "myderp"})
    assert r["ok"] and r["path"] == "derp:myderp" and r["rtt_ms"] == 45.0
    assert parse_pingresult({"Err": "timeout"})["ok"] is False
    assert parse_pingresult({"LatencySeconds": 0})["ok"] is False     # chua co RTT
    assert parse_pingresult(None)["ok"] is False


def test_is_tailnet_ip():
    assert is_tailnet_ip("100.64.0.3") is True          # dai Tailscale v4
    assert is_tailnet_ip("100.127.255.255") is True
    assert is_tailnet_ip("127.0.0.1") is True           # loopback OK (debug local)
    assert is_tailnet_ip("fd7a:115c:a1e0::1") is True   # dai Tailscale v6
    assert is_tailnet_ip("10.121.5.18") is False        # LAN noi bo -> tu choi
    assert is_tailnet_ip("8.8.8.8") is False            # internet -> tu choi
    assert is_tailnet_ip("100.128.0.1") is False        # ngoai 100.64/10
    assert is_tailnet_ip("khong-phai-ip") is False


def test_is_allowed_report_src():
    # tailnet + loopback van duoc
    assert is_allowed_report_src("100.64.0.3") is True
    assert is_allowed_report_src("127.0.0.1") is True
    # mang docker noi bo (node bao cao qua forwarder ts-forward) -> duoc
    assert is_allowed_report_src("172.18.0.7") is True   # dai docker bridge
    assert is_allowed_report_src("10.0.0.5") is True
    assert is_allowed_report_src("192.168.1.10") is True
    # internet -> tu choi
    assert is_allowed_report_src("8.8.8.8") is False
    assert is_allowed_report_src("khong-phai-ip") is False


def test_latency_series_groups_sorts_drops_bad():
    rows = [
        {"src": "itop", "dst": "votam", "rtt_ms": 10.0, "path": "direct", "ok": True, "ts": 3},
        {"src": "itop", "dst": "votam", "rtt_ms": 12.0, "path": "direct", "ok": True, "ts": 1},
        {"src": "itop", "dst": "votam", "rtt_ms": None, "path": "", "ok": False, "ts": 2},
    ]
    s = latency_series(rows)
    assert len(s) == 1 and s[0]["pair"] == "itop -> votam"
    assert [p["t"] for p in s[0]["points"]] == [1, 3]   # sorted, bad dropped


def test_query_devices():
    conn = _mem_db()
    conn.execute("INSERT INTO devices(user,hostname,mac,node_id,ipv4,machine_key,first_seen,last_seen,seen_count)"
                 " VALUES('u','itop','AA:BB','1','100.64.0.1','mk',0,0,5)")
    conn.commit()
    d = query_devices(conn)
    assert len(d) == 1 and d[0]["hostname"] == "itop"
    assert d[0]["mac"] == "AA:BB" and d[0]["seen_count"] == 5


def test_render_stats_html_smoke():
    import json as _j
    pairs = [{"src": "itop", "dst": "votam", "count": 2, "min_ms": 10.0, "avg_ms": 11.0,
              "max_ms": 12.0, "ok_pct": 100.0, "direct_pct": 100.0,
              "last_ms": 12.0, "last_path": "direct", "last_ts": 2}]
    series = [{"pair": "itop -> votam", "points": [{"t": 1, "rtt": 10.0}, {"t": 2, "rtt": 12.0}]}]
    devices = [{"hostname": "itop", "mac": "AA:BB", "ipv4": "100.64.0.1", "last_seen": 0, "seen_count": 2}]
    page = render_stats_html(pairs, series, devices, 3600, 1000)
    assert "<html" in page and "Chart" in page
    assert "__DATA__" not in page          # placeholder da thay
    assert "itop" in page and "votam" in page
    frag = page.split("const D = ", 1)[1].split(";", 1)[0]
    data = _j.loads(frag)
    assert data["pairs"][0]["src"] == "itop" and data["window_min"] == 60


def test_record_report_mac_fallback_by_hostname():
    conn = _mem_db()
    conn.execute("INSERT INTO devices(user,hostname,mac,node_id,ipv4,machine_key,first_seen,last_seen,seen_count)"
                 " VALUES('u','votam',NULL,'2','','mk2',0,0,1)")  # chua co ipv4
    conn.commit()
    rep = validate_report({"hostname": "votam", "ipv4": "100.64.0.9", "mac": "11:22:33", "samples": []})
    record_report(conn, rep, 1)
    assert conn.execute("SELECT mac FROM devices WHERE hostname='votam'").fetchone()[0] == "11:22:33"


# ---------------- DERP status ----------------

def test_parse_derp_regions_two_regions():
    regions = _parse_derp_regions(
        "myderp=https://vpn2.hangocthanh.io.vn/derp/probe,"
        "vpn4-vn=https://vpn4.hangocthanh.io.vn/derp/probe"
    )
    assert len(regions) == 2
    assert regions[0] == {"code": "myderp", "url": "https://vpn2.hangocthanh.io.vn/derp/probe"}
    assert regions[1]["code"] == "vpn4-vn"


def test_parse_derp_regions_three_regions():
    regions = _parse_derp_regions(
        "myderp=https://vpn2.hangocthanh.io.vn/derp/probe,"
        "vpn4-vn=https://vpn4.hangocthanh.io.vn/derp/probe,"
        "vpn5-us=https://vpn5.hangocthanh.io.vn/derp/probe"
    )
    assert len(regions) == 3
    assert regions[2] == {"code": "vpn5-us", "url": "https://vpn5.hangocthanh.io.vn/derp/probe"}


def test_parse_derp_regions_empty():
    assert _parse_derp_regions("") == []
    assert _parse_derp_regions(None) == []


def test_probe_derp_region_ok():
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        r = probe_derp_region("https://example.com/derp/probe")
    assert r["ok"] is True and r["error"] is None
    assert r["latency_ms"] is not None and r["latency_ms"] >= 0


def test_probe_derp_region_fail():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        r = probe_derp_region("https://example.com/derp/probe")
    assert r["ok"] is False
    assert "connection refused" in (r["error"] or "")


def test_query_current_relay_picks_latest():
    conn = _mem_db()
    now = int(time.time())
    conn.executemany(
        "INSERT INTO node_latency(ts,src,dst,dst_ip,rtt_ms,path,ok) VALUES(?,?,?,?,?,?,?)",
        [
            (now - 5, "collector", "server1", "100.64.0.5", 20.0, "derp:myderp", 1),
            (now,     "collector", "server1", "100.64.0.5", 15.0, "derp:vpn4-vn", 1),  # moi nhat
            (now,     "collector", "phone1",  "100.64.0.6",  2.0, "direct", 1),
        ],
    )
    conn.commit()
    rows = query_current_relay(conn, window=300)
    by_host = {r["hostname"]: r for r in rows}
    assert by_host["server1"]["relay"] == "derp:vpn4-vn"   # lan moi nhat
    assert by_host["phone1"]["relay"] == "direct"


def test_query_current_relay_respects_window():
    conn = _mem_db()
    now = int(time.time())
    conn.execute(
        "INSERT INTO node_latency(ts,src,dst,dst_ip,rtt_ms,path,ok) VALUES(?,?,?,?,?,?,?)",
        (now - 500, "collector", "old-node", "100.64.0.9", 8.0, "direct", 1),
    )
    conn.commit()
    rows = query_current_relay(conn, window=60)   # cua so nho -> khong thay
    assert not any(r["hostname"] == "old-node" for r in rows)


def test_peer_relay_from_status_relay_and_direct():
    status = {
        "Peer": {
            "nodekey:aaa": {
                "HostName": "server1",
                "TailscaleIPs": ["100.64.0.5", "fd7a::5"],
                "Relay": "vpn4-vn",
                "CurAddr": "",          # khong di thang
                "Online": True,
            },
            "nodekey:bbb": {
                "HostName": "phone1",
                "TailscaleIPs": ["100.64.0.6"],
                "Relay": "myderp",
                "CurAddr": "1.2.3.4:41641",  # di thang P2P
                "Online": True,
            },
            "nodekey:ccc": {
                "HostName": "laptop",
                "TailscaleIPs": ["100.64.0.7"],
                "Relay": "",
                "CurAddr": "",
                "Online": False,        # offline
            },
        }
    }
    peers = peer_relay_from_status(status)
    by_host = {p["hostname"]: p for p in peers}

    assert by_host["server1"]["relay"] == "vpn4-vn"
    assert by_host["server1"]["direct"] is False
    assert by_host["server1"]["online"] is True

    assert by_host["phone1"]["relay"] == "myderp"
    assert by_host["phone1"]["direct"] is True   # CurAddr non-empty -> direct P2P

    assert by_host["laptop"]["online"] is False


def test_peer_relay_from_status_empty():
    assert peer_relay_from_status(None) == []
    assert peer_relay_from_status({}) == []
    assert peer_relay_from_status({"Peer": {}}) == []


def test_render_derp_html_smoke():
    regions = [
        {"code": "myderp",  "url": "https://vpn2.../probe", "ok": True,  "latency_ms": 12.0, "error": None},
        {"code": "vpn4-vn", "url": "https://vpn4.../probe", "ok": True,  "latency_ms": 25.0, "error": None},
    ]
    peers = [
        {"hostname": "server1", "ip": "100.64.0.5", "relay": "vpn4-vn", "direct": False, "online": True},
        {"hostname": "phone1",  "ip": "100.64.0.6", "relay": "myderp",  "direct": True,  "online": True},
    ]
    page = render_derp_html(regions, peers, 1200)
    assert "<html" in page
    assert "myderp" in page and "vpn4-vn" in page
    assert "server1" in page and "phone1" in page
    assert "direct" in page
    assert "__GENERATED__" not in page
    assert "__REGIONS__" not in page
    assert "__ROWS__" not in page


def test_render_derp_html_dead_relay_warning():
    """Node dung relay chet phai hien badge canh bao (derp-dead), khong phai badge binh thuong."""
    regions = [
        {"code": "myderp",  "url": "https://vpn2.../probe", "ok": True,  "latency_ms": 12.0, "error": None},
        {"code": "vpn4-vn", "url": "https://vpn4.../probe", "ok": False, "latency_ms": None, "error": "timeout"},
    ]
    peers = [
        {"hostname": "itop", "ip": "100.64.0.2", "relay": "vpn4-vn", "direct": False, "online": True},
    ]
    page = render_derp_html(regions, peers, 1200)
    assert "derp-dead" in page, "itop dung vpn4-vn (chet) phai hien badge canh bao"
    assert "9888" in page or "&#9888;" in page, "phai co icon canh bao &#9888;"


def test_render_derp_html_empty_peers():
    regions = [{"code": "myderp", "url": "https://x/probe", "ok": True, "latency_ms": 5.0, "error": None}]
    page = render_derp_html(regions, [], 1000)
    assert "collector" in page.lower() or "Ch" in page


# ---------------- client_netcheck ----------------

def test_record_and_query_netcheck_basic():
    """record_netcheck + query_latest_netcheck roundtrip."""
    conn = _mem_db()
    now = int(time.time())
    rl = json.dumps({"vpn4-vn": 25.3, "myderp": 137.7, "vpn5-us": None})
    record_netcheck(conn, "itop", "vpn4-vn", rl, now)
    rows = query_latest_netcheck(conn, window=300)
    assert len(rows) == 1
    assert rows[0]["client"] == "itop"
    assert rows[0]["preferred_derp"] == "vpn4-vn"
    assert rows[0]["region_latency"]["vpn4-vn"] == 25.3
    assert rows[0]["region_latency"]["vpn5-us"] is None


def test_query_latest_netcheck_window_expired():
    """Ban cu vuot qua window khong duoc tra ve."""
    conn = _mem_db()
    now = int(time.time())
    record_netcheck(conn, "itop", "vpn4-vn", '{}', now - 700)
    rows = query_latest_netcheck(conn, window=600)
    assert rows == []


def test_query_latest_netcheck_latest_per_client():
    """Moi client chi tra ve ban moi nhat."""
    conn = _mem_db()
    now = int(time.time())
    record_netcheck(conn, "itop", "myderp", '{"myderp": 50.0}', now - 10)
    record_netcheck(conn, "itop", "vpn4-vn", '{"vpn4-vn": 25.3}', now)
    rows = query_latest_netcheck(conn, window=300)
    assert len(rows) == 1
    assert rows[0]["preferred_derp"] == "vpn4-vn"


def test_render_derp_html_all_pings_source_column():
    """all_pings hien thi cot Nguon (vpn2/vpn4) voi RTT va path tag."""
    regions = [
        {"code": "myderp",  "url": "https://vpn2.../probe", "ok": True, "latency_ms": 12.0, "error": None},
        {"code": "vpn4-vn", "url": "https://vpn4.../probe", "ok": True, "latency_ms": 25.0, "error": None},
    ]
    all_pings = {
        "collector": [
            {"hostname": "itop",  "ip": "100.64.0.2", "relay": "derp:vpn4-vn",
             "rtt_ms": 95.6, "ok": True, "ts": 1000},
            {"hostname": "votam", "ip": "100.64.0.3", "relay": "derp:vpn4-vn",
             "rtt_ms": 148.9, "ok": True, "ts": 1000},
        ],
        # vpn4: no data yet
    }
    page = render_derp_html(regions, [], 1000, all_pings=all_pings)
    assert "vpn2" in page                  # row nguon vpn2
    assert "vpn4" in page                  # row nguon vpn4 (placeholder)
    assert "95.6ms" in page and "148.9ms" in page   # vpn2 data
    assert "via vpn4-vn" in page           # path tag vpn2->itop
    assert "__PINGS__" not in page


def test_render_derp_html_all_pings_empty():
    """all_pings={}: tat ca nguon hien placeholder 'chua co du lieu'."""
    regions = [
        {"code": "myderp",  "url": "https://vpn2.../probe", "ok": True, "latency_ms": 12.0, "error": None},
        {"code": "vpn4-vn", "url": "https://vpn4.../probe", "ok": True, "latency_ms": 25.0, "error": None},
    ]
    page = render_derp_html(regions, [], 1000, all_pings={})
    assert "vpn2" in page and "vpn4" in page
    assert "__PINGS__" not in page


def test_render_derp_html_no_pings():
    """all_pings=None: vpn2/vpn4 row van hien placeholder."""
    regions = [
        {"code": "myderp",  "url": "https://x/probe", "ok": True, "latency_ms": 5.0, "error": None},
        {"code": "vpn4-vn", "url": "https://x/probe", "ok": True, "latency_ms": 5.0, "error": None},
    ]
    page = render_derp_html(regions, [], 1000, all_pings=None)
    assert "vpn2" in page and "vpn4" in page
    assert "__PINGS__" not in page


def test_query_all_server_pings_multi_src():
    """query_all_server_pings tra ve dict {src: [peers]} cho moi src."""
    conn = _mem_db()
    now = int(time.time())
    conn.executemany(
        "INSERT INTO node_latency(ts,src,dst,dst_ip,rtt_ms,path,ok) VALUES(?,?,?,?,?,?,?)",
        [
            (now, "collector", "itop",  "100.64.0.2", 95.6,  "derp:vpn4-vn", 1),
            (now, "collector", "votam", "100.64.0.3", 148.9, "derp:vpn4-vn", 1),
            (now, "vpn4",      "itop",  "100.64.0.2", 25.3,  "direct",       1),
        ],
    )
    conn.commit()
    result = query_all_server_pings(conn, window=300)
    assert set(result.keys()) == {"collector", "vpn4"}
    assert len(result["collector"]) == 2
    assert result["vpn4"][0]["hostname"] == "itop" and result["vpn4"][0]["rtt_ms"] == 25.3


def test_query_all_server_pings_picks_latest():
    """Chi lay lan ping moi nhat per (src, dst)."""
    conn = _mem_db()
    now = int(time.time())
    conn.executemany(
        "INSERT INTO node_latency(ts,src,dst,dst_ip,rtt_ms,path,ok) VALUES(?,?,?,?,?,?,?)",
        [
            (now - 10, "vpn4", "itop", "100.64.0.2", 50.0, "derp:myderp", 1),
            (now,      "vpn4", "itop", "100.64.0.2", 25.3, "direct",      1),  # moi hon
        ],
    )
    conn.commit()
    result = query_all_server_pings(conn, window=300)
    assert result["vpn4"][0]["relay"] == "direct"    # moi nhat
    assert result["vpn4"][0]["rtt_ms"] == 25.3


def test_query_all_server_pings_window():
    """Row ngoai window khong duoc tra ve."""
    conn = _mem_db()
    now = int(time.time())
    conn.execute(
        "INSERT INTO node_latency(ts,src,dst,dst_ip,rtt_ms,path,ok) VALUES(?,?,?,?,?,?,?)",
        (now - 500, "vpn4", "itop", "100.64.0.2", 25.0, "direct", 1),
    )
    conn.commit()
    assert query_all_server_pings(conn, window=60) == {}


def test_render_derp_html_ajax_refresh():
    """Trang /derp dung AJAX fetch moi 5s thay vi meta refresh."""
    regions = [{"code": "myderp", "url": "https://x/probe",
                "ok": True, "latency_ms": 5.0, "error": None}]
    page = render_derp_html(regions, [], 1000)
    assert "meta http-equiv" not in page    # khong dung meta refresh
    assert "setInterval" in page            # dung JS setInterval
    assert "5000" in page                   # interval 5 giay
    assert "fetch(" in page                 # AJAX fetch
