#!/usr/bin/env python3
"""Stub oauth2-proxy cho test tich hop /stats (KHONG dung Google -> deterministic).

Caddy forward_auth goi GET /oauth2/auth:
  - co cookie 'testauth=1'  -> 202 (gia lap DA dang nhap)  -> Caddy di tiep reverse_proxy
  - khong co               -> 401                          -> Caddy redirect 302 /oauth2/start
Cac path khac tra 200 (du de redirect toi).
"""
import http.server


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _end(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/oauth2/auth"):
            cookie = self.headers.get("Cookie", "")
            self._end(202 if "testauth=1" in cookie else 401)
            return
        self._end(200)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", 4180), H).serve_forever()
