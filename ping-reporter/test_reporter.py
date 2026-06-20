"""Unit test cho reporter.py: get_peers_and_collector."""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
from reporter import get_peers_and_collector


def _make_status(peers_data):
    peer_dict = {}
    for i, p in enumerate(peers_data):
        peer_dict["nodekey:%03d" % i] = p
    return {"Peer": peer_dict}


def _mock_status(status_obj):
    return patch("reporter._localapi", return_value=status_obj)


def test_collector_found_when_online():
    status = _make_status([
        {"HostName": "collector", "TailscaleIPs": ["100.64.0.1", "fd7a::1"], "Online": True},
        {"HostName": "itop",      "TailscaleIPs": ["100.64.0.2"],             "Online": True},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip == "100.64.0.1"
    assert peers == [("itop", "100.64.0.2")]


def test_collector_found_even_when_offline():
    # fix: collector.Online=False khong duoc chan truoc khi kiem tra hostname
    status = _make_status([
        {"HostName": "collector", "TailscaleIPs": ["100.64.0.1"], "Online": False},
        {"HostName": "itop",      "TailscaleIPs": ["100.64.0.2"], "Online": True},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip == "100.64.0.1"
    assert peers == [("itop", "100.64.0.2")]


def test_collector_not_in_tailnet():
    status = _make_status([
        {"HostName": "itop", "TailscaleIPs": ["100.64.0.2"], "Online": True},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip is None
    assert peers == [("itop", "100.64.0.2")]


def test_offline_non_collector_not_pinged():
    status = _make_status([
        {"HostName": "collector", "TailscaleIPs": ["100.64.0.1"], "Online": True},
        {"HostName": "itop",      "TailscaleIPs": ["100.64.0.2"], "Online": False},
        {"HostName": "votam",     "TailscaleIPs": ["100.64.0.3"], "Online": True},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip == "100.64.0.1"
    host_names = [h for h, _ in peers]
    assert "votam" in host_names
    assert "itop" not in host_names  # offline -> khong ping


def test_dns_name_fallback():
    status = _make_status([
        {"HostName": "", "DNSName": "collector.votam.vpn2.example.com",
         "TailscaleIPs": ["100.64.0.1"], "Online": True},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip == "100.64.0.1"


def test_no_ipv4_peer_skipped():
    # peer chi co IPv6 -> bo qua
    status = _make_status([
        {"HostName": "collector", "TailscaleIPs": ["fd7a::1"], "Online": True},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip is None


def test_localapi_unreachable():
    with _mock_status(None):
        peers, collector_ip = get_peers_and_collector()
    assert peers == [] and collector_ip is None


def test_empty_peer_list():
    with _mock_status({"Peer": {}}):
        peers, collector_ip = get_peers_and_collector()
    assert peers == [] and collector_ip is None


def test_prefers_online_collector_over_offline_duplicate():
    # Sau deploy/churn: 2 node 'collector' - ban cu OFFLINE (IP .9) + ban moi ONLINE
    # (IP .1). Reporter PHAI chon ban ONLINE de khong POST vao IP chet.
    status = _make_status([
        {"HostName": "collector", "TailscaleIPs": ["100.64.0.9"], "Online": False},
        {"HostName": "collector", "TailscaleIPs": ["100.64.0.1"], "Online": True},
        {"HostName": "itop",      "TailscaleIPs": ["100.64.0.2"], "Online": True},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip == "100.64.0.1"  # ban ONLINE, khong phai .9 offline


def test_all_peers_offline_collector_still_found():
    # Tat ca offline (sau khi join tailnet, truoc khi disco hoan thanh) nhung
    # collector van phai duoc tim thay de POST.
    status = _make_status([
        {"HostName": "collector", "TailscaleIPs": ["100.64.0.1"], "Online": False},
        {"HostName": "votam",     "TailscaleIPs": ["100.64.0.3"], "Online": False},
        {"HostName": "itop",      "TailscaleIPs": ["100.64.0.2"], "Online": False},
    ])
    with _mock_status(status):
        peers, collector_ip = get_peers_and_collector()
    assert collector_ip == "100.64.0.1"
    assert peers == []  # khong co peer online de ping
