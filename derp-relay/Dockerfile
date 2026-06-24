FROM golang:1.23-alpine AS builder
# Cung version voi cac node DERP khac (derp-vpn3/4/5/6) de dong nhat.
ARG TAILSCALE_VERSION=v1.80.0
RUN go install tailscale.com/cmd/derper@${TAILSCALE_VERSION}

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=builder /go/bin/derper /usr/bin/derper
# 3340/tcp: DERP over HTTP (Caddy terminate TLS). 3478/udp: STUN truc tiep.
EXPOSE 3340/tcp 3478/udp
ENTRYPOINT ["derper"]
