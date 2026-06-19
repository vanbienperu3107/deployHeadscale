# Stage 1: Build
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download

COPY *.go ./
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
