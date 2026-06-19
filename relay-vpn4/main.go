package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"tailscale.com/types/key"
)

func main() {
	var (
		addr     = flag.String("addr", ":8080", "TCP listen address (HTTP, behind Traefik)")
		tsSocket = flag.String("ts-socket", "/var/run/tailscale/tailscaled.sock", "Tailscale sidecar socket")
		cacheTTL = flag.Duration("cache-ttl", 5*time.Second, "Endpoint cache refresh interval")
		keyFile  = flag.String("key-file", "/data/relay.key", "Path to persist server private key")
	)
	flag.Parse()

	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Printf("vpn4 hybrid relay starting — listen %s", *addr)

	priv := loadOrGenKey(*keyFile)
	log.Printf("server pubkey: %v", priv.Public())

	epCache := NewEndpointCache(*tsSocket, *cacheTTL)
	sessions := NewSessionTable()
	srv := NewServer(priv, epCache, sessions)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go epCache.Run(ctx)

	httpSrv := &http.Server{
		Addr:        *addr,
		Handler:     srv.Handler(),
		ReadTimeout: 0,
		WriteTimeout: 0,
		IdleTimeout: 120 * time.Second,
	}

	go func() {
		log.Printf("HTTP server listening on %s", *addr)
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("HTTP server: %v", err)
		}
	}()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigCh
	log.Printf("received %v, shutting down", sig)

	shutCtx, shutCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutCancel()
	httpSrv.Shutdown(shutCtx)
	cancel()
	log.Printf("relay stopped")
}

func loadOrGenKey(path string) key.NodePrivate {
	if data, err := os.ReadFile(path); err == nil {
		var k key.NodePrivate
		if err := k.UnmarshalText(data); err == nil {
			log.Printf("loaded server key from %s (pubkey: %v)", path, k.Public())
			return k
		}
		log.Printf("warn: key file %s is corrupt, generating new key", path)
	}

	k := key.NewNode()
	txt, err := k.MarshalText()
	if err != nil {
		log.Fatalf("marshal new key: %v", err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		log.Printf("warn: cannot create key dir %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, txt, 0600); err != nil {
		log.Printf("warn: cannot persist key to %s: %v (key will rotate on restart)", path, err)
	} else {
		log.Printf("generated new server key, saved to %s", path)
	}
	return k
}
