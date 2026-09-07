#!/usr/bin/env python3
"""Pre-flight cho viec bat --verify-client-url tren derper.

CHI DOC. Khong thay doi bat cu thu gi tren server.

Tra loi 3 cau hoi cua Giai doan 0 + buoc 1.2 trong
docs/plan-derp-verify-clients.md:

  0.1  endpoint POST /verify cua headscale co song khong?
       (nodekey rac -> phai tra ve Allow:false)
  0.2  nodekey THAT co duoc allow khong?
       (neu khong -> sai dinh dang key, DUNG, khong bat co nao)
  1.2  node NAO trong fleet se bi tu choi khi bat co?

Bien moi truong:
  HS_URL      base URL cua headscale (vd https://vpn2.hangocthanh.io.vn)
  HS_API_KEY  api key headscale (Bearer)

Exit code:
  0 = an toan de sang Giai doan 1
  1 = DUNG, co van de phai xu ly truoc
"""

import json
import os
import sys
import urllib.error
import urllib.request

HS_URL = os.environ.get("HS_URL", "").rstrip("/")
HS_API_KEY = os.environ.get("HS_API_KEY", "")
TIMEOUT = 20

# nodekey chac chan khong ton tai trong bat ky tailnet nao
DUMMY_KEY = "nodekey:" + "00" * 32


def http(url, method="GET", body=None, headers=None):
    """Tra ve (status, text). Khong nem exception cho loi HTTP."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # timeout, DNS, TLS...
        return 0, f"{type(e).__name__}: {e}"


def verify(node_public):
    """POST /verify -> (status, allow|None, raw)."""
    status, text = http(
        f"{HS_URL}/verify",
        method="POST",
        body={"NodePublic": node_public, "Source": "203.0.113.1"},
    )
    allow = None
    if status == 200:
        try:
            allow = bool(json.loads(text).get("Allow"))
        except Exception:
            allow = None
    return status, allow, text.strip()[:200]


def main():
    if not HS_URL:
        print("::error::thieu HS_URL")
        return 1

    print(f"headscale: {HS_URL}")
    print("=" * 60)

    # ---- 0.1 endpoint co song khong -------------------------------------
    print("\n[0.1] POST /verify voi nodekey rac (ky vong: 200 + Allow:false)")
    status, allow, raw = verify(DUMMY_KEY)
    print(f"      HTTP {status}  Allow={allow}  body={raw!r}")
    if status != 200:
        print(f"::error::[0.1] FAIL - /verify tra ve HTTP {status}, khong phai 200.")
        print("::error::Endpoint khong ton tai hoac khong reach duoc. DUNG.")
        return 1
    if allow is not False:
        print("::error::[0.1] FAIL - nodekey rac ma van duoc Allow (hoac body la).")
        print("::error::Endpoint khong hanh xu dung nhu admission controller. DUNG.")
        return 1
    print("      [0.1] PASS")

    # ---- lay danh sach node ---------------------------------------------
    if not HS_API_KEY:
        print("\n::error::thieu HS_API_KEY - khong lam duoc 0.2 va 1.2")
        return 1

    print("\n[..] Lay danh sach node tu headscale API")
    status, text = http(
        f"{HS_URL}/api/v1/node",
        headers={"Authorization": f"Bearer {HS_API_KEY}"},
    )
    if status != 200:
        print(f"::error::GET /api/v1/node -> HTTP {status}: {text[:300]}")
        return 1
    nodes = json.loads(text).get("nodes", [])
    print(f"     {len(nodes)} node")
    if not nodes:
        print("::error::Fleet rong - khong the xac minh 0.2. DUNG.")
        return 1

    # In dinh dang key thuc te de doi chieu (bai hoc nodekey-format-asymmetry)
    sample = nodes[0].get("nodeKey", "")
    print(f"     dinh dang nodeKey mau: {sample!r}")

    # ---- 0.2 + 1.2 kiem tung node ---------------------------------------
    print("\n[0.2 + 1.2] Kiem tung node qua /verify")
    print("-" * 60)
    allowed, denied, errored = [], [], []
    for n in nodes:
        name = n.get("givenName") or n.get("name") or f"id={n.get('id')}"
        key = n.get("nodeKey", "")
        online = n.get("online")
        if not key:
            errored.append((name, "khong co nodeKey"))
            print(f"  ?  {name:<28} (khong co nodeKey trong API)")
            continue
        status, allow, raw = verify(key)
        if status != 200 or allow is None:
            errored.append((name, f"HTTP {status} {raw}"))
            print(f"  ?  {name:<28} HTTP {status} {raw}")
        elif allow:
            allowed.append(name)
            print(f"  OK {name:<28} Allow=true  (online={online})")
        else:
            denied.append(name)
            print(f"  XX {name:<28} Allow=FALSE (online={online})  <-- SE BI CHAN")

    # ---- ket luan --------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"TONG: {len(allowed)} allow / {len(denied)} bi chan / {len(errored)} loi")

    if not allowed:
        print("\n::error::[0.2] FAIL - KHONG node nao duoc Allow.")
        print("::error::Gan nhu chac chan la sai dinh dang nodekey giua API va /verify.")
        print("::error::TUYET DOI KHONG bat --verify-client-url. DUNG.")
        return 1
    print(f"\n[0.2] PASS - {len(allowed)} node duoc allow bang nodekey that")

    if denied:
        print("\n::error::[1.2] FAIL - co node se mat relay khi bat co:")
        for name in denied:
            print(f"::error::  - {name}")
        print("::error::Xu ly cac node nay (re-join / don nodekey cu) TRUOC khi bat co.")
        return 1

    if errored:
        print("\n::warning::[1.2] Co node khong kiem duoc, xem lai truoc khi bat co:")
        for name, why in errored:
            print(f"::warning::  - {name}: {why}")
        return 1

    print("\n[1.2] PASS - toan bo fleet duoc allow.")
    print("=> AN TOAN sang Giai doan 1 (bat --verify-client-url voi fail-open=true).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
