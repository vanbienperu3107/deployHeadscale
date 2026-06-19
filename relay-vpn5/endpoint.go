package main

import (
	"context"
	"log"
	"net/netip"
	"sync"
	"time"

	tailscaleclient "tailscale.com/client/tailscale"
	"tailscale.com/ipn/ipnstate"
	"tailscale.com/types/key"
)

// EndpointCache queries the local Tailscale sidecar (via Unix socket)
// to discover which peers have reachable UDP endpoints.
//
// Detection logic:
//   PeerStatus.CurAddr != "" && PeerStatus.Relay == ""
//     → peer is directly reachable via UDP from vpn5 → USE UDP
//   PeerStatus.CurAddr == "" || PeerStatus.Relay != ""
//     → peer is TCP-only or no path yet → USE TCP DERP fallback
type EndpointCache struct {
	lc *tailscaleclient.LocalClient

	mu      sync.RWMutex
	peers   map[key.NodePublic]*ipnstate.PeerStatus
	updated time.Time
	ttl     time.Duration
}

func NewEndpointCache(socketPath string, ttl time.Duration) *EndpointCache {
	return &EndpointCache{
		lc:    &tailscaleclient.LocalClient{Socket: socketPath},
		peers: make(map[key.NodePublic]*ipnstate.PeerStatus),
		ttl:   ttl,
	}
}

// Resolve returns the best UDP endpoint for destKey.
// Returns (addr, true) if UDP is usable; (zero, false) if only TCP is available.
//
// Priority:
//  1. CurAddr (sidecar's currently active direct path) — most reliable
//  2. First public addr in Addrs list (sidecar knows but not actively using)
func (c *EndpointCache) Resolve(ctx context.Context, destKey key.NodePublic) (netip.AddrPort, bool) {
	peer := c.getPeer(ctx, destKey)
	if peer == nil {
		return netip.AddrPort{}, false
	}

	// Best case: sidecar has an active direct UDP path to this peer right now.
	// CurAddr is empty if the peer is reachable only via DERP relay.
	if peer.CurAddr != "" && peer.Relay == "" {
		ap, err := netip.ParseAddrPort(peer.CurAddr)
		if err == nil && ap.IsValid() {
			return ap, true
		}
	}

	// Fallback: sidecar knows candidate endpoints but hasn't confirmed them yet.
	// Try the first public (non-loopback, non-private) endpoint.
	for _, addr := range peer.Addrs {
		ap, err := netip.ParseAddrPort(addr)
		if err != nil {
			continue
		}
		ip := ap.Addr()
		if ip.IsLoopback() || ip.IsPrivate() || ip.IsUnspecified() {
			continue
		}
		return ap, true // optimistic: try UDP, session.go handles failure
	}

	return netip.AddrPort{}, false // peer is TCP-only
}

// IsUDPCapable returns true if the peer is known to have a reachable UDP endpoint.
// Used to decide routing: UDP or TCP DERP.
func (c *EndpointCache) IsUDPCapable(ctx context.Context, k key.NodePublic) bool {
	_, ok := c.Resolve(ctx, k)
	return ok
}

// Invalidate clears the cached entry for a peer, forcing a refresh on next lookup.
// Called when a UDP send fails, so we don't keep sending to a dead endpoint.
func (c *EndpointCache) Invalidate(k key.NodePublic) {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.peers, k)
}

// Run periodically refreshes the peer map from the sidecar.
// Call in a goroutine; stops when ctx is cancelled.
func (c *EndpointCache) Run(ctx context.Context) {
	c.refresh(ctx) // immediate first fetch
	ticker := time.NewTicker(c.ttl)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			c.refresh(ctx)
		}
	}
}

func (c *EndpointCache) getPeer(ctx context.Context, k key.NodePublic) *ipnstate.PeerStatus {
	c.mu.RLock()
	fresh := time.Since(c.updated) < c.ttl
	p := c.peers[k]
	c.mu.RUnlock()

	if fresh && p != nil {
		return p
	}

	// Cache miss or stale: refresh synchronously.
	c.refresh(ctx)

	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.peers[k]
}

func (c *EndpointCache) refresh(ctx context.Context) {
	st, err := c.lc.Status(ctx)
	if err != nil {
		log.Printf("endpoint cache: sidecar status error: %v", err)
		return
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	c.peers = st.Peer
	c.updated = time.Now()

	// Log UDP-capable peers for visibility
	udpCount, tcpCount := 0, 0
	for _, p := range st.Peer {
		if p.CurAddr != "" && p.Relay == "" {
			udpCount++
		} else {
			tcpCount++
		}
	}
	log.Printf("endpoint cache refreshed: %d peers (%d UDP-capable, %d TCP-only)", len(st.Peer), udpCount, tcpCount)
}
