"""Unit test cho logic dedup + collector (chay trong CI truoc khi deploy)."""
import sqlite3

import pytest

from dedup import (aggregate_latency, init_db, init_latency_db, normalize,
                   plan_actions, record_report, validate_report)


def mk(id, host, given, user="u", online=False, last=0):
    return {"id": id, "hostname": host, "given_name": given,
            "user": user, "online": online, "last_seen": last,
            "ips": [], "machine_key": ""}


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


def test_record_report_mac_fallback_by_hostname():
    conn = _mem_db()
    conn.execute("INSERT INTO devices(user,hostname,mac,node_id,ipv4,machine_key,first_seen,last_seen,seen_count)"
                 " VALUES('u','votam',NULL,'2','','mk2',0,0,1)")  # chua co ipv4
    conn.commit()
    rep = validate_report({"hostname": "votam", "ipv4": "100.64.0.9", "mac": "11:22:33", "samples": []})
    record_report(conn, rep, 1)
    assert conn.execute("SELECT mac FROM devices WHERE hostname='votam'").fetchone()[0] == "11:22:33"
