#!/usr/bin/env python3
"""Bootstrap Beszel: auth superuser -> tao user admin + system vpn6/vpn4 (idempotent).
Env: BESZEL_PASS (mat khau superuser + user admin). Chay tren vpn6, hub o 127.0.0.1:8090.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8090/api/collections"
EMAIL = "admin@hangocthanh.io.vn"
PASS = os.environ["BESZEL_PASS"]


def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    r = urllib.request.Request(
        BASE + path, method=method, headers=headers,
        data=json.dumps(data).encode() if data is not None else None)
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return {"_err": e.read().decode()}


def main():
    auth = req("POST", "/_superusers/auth-with-password",
               {"identity": EMAIL, "password": PASS})
    token = auth.get("token")
    if not token:
        sys.exit("superuser auth fail: %s" % auth)

    flt = urllib.parse.quote("email='%s'" % EMAIL)
    users = req("GET", "/users/records?filter=" + flt, token=token)
    if users.get("items"):
        uid = users["items"][0]["id"]
        print("user admin da ton tai:", uid)
    else:
        u = req("POST", "/users/records",
                {"email": EMAIL, "password": PASS, "passwordConfirm": PASS,
                 "role": "admin", "verified": True}, token=token)
        uid = u.get("id")
        if not uid:
            sys.exit("tao user fail: %s" % u)
        print("da tao user admin:", uid)

    have = {s["name"] for s in
            req("GET", "/systems/records?perPage=100", token=token).get("items", [])}
    for name, host in [("vpn6", "host.docker.internal"), ("vpn4", "149.104.66.174")]:
        if name in have:
            print(name, "da ton tai")
            continue
        s = req("POST", "/systems/records",
                {"name": name, "host": host, "port": "45876",
                 "users": [uid], "status": "pending"}, token=token)
        print(name, "->", "OK " + s["id"] if s.get("id") else s)


if __name__ == "__main__":
    main()
