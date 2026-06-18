"""Unit test cho logic dedup (chay trong CI truoc khi deploy)."""
from dedup import plan_actions, normalize


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
