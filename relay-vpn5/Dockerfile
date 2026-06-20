# Stage 1: Build
FROM golang:1.24-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /src
COPY go.mod go.sum* ./
COPY *.go ./
# Repo khong commit go.sum -> go mod tidy sinh go.sum tu cac import luc build
# (can mang, co san trong CI/server). Tranh loi "missing go.sum entry".
RUN go mod tidy

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /relay .

# Stage 2: Run
FROM alpine:3.19

RUN apk add --no-cache ca-certificates tzdata

WORKDIR /app
COPY --from=builder /relay /app/relay

# /data is a volume for the persistent server key
VOLUME ["/data"]

ENTRYPOINT ["/app/relay"]
CMD ["-addr=:8080", "-ts-socket=/var/run/tailscale/tailscaled.sock", "-key-file=/data/relay.key"]
