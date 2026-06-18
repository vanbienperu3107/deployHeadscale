# Caddy + plugin replace-response: de chen 1 nut noi "Thong ke" vao trang
# Headplane (/admin) - vi Headplane (app ben thu 3) khong cho them link trong config.
FROM caddy:2-builder AS builder
RUN xcaddy build --with github.com/caddyserver/replace-response

FROM caddy:2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
