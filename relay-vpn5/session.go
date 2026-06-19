package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/netip"
	"sync"

	"tailscale.com/types/key"
)

// sessionKey identifies a (src, dst) peer pair.
type sessionKey struct {
	src key.NodePublic
	dst key.NodePublic
}

// Session holds the UDP socket for one (src→dst) relay path.
// Each session has its own ephemeral UDP socket on vpn5, so:
//   - All replies from dst arrive on this socket (unambiguous)
//   - Multiple sessions to the same dst use different source ports
type Session struct {
	srcKey  key.NodePublic
	dstKey  key.NodePublic
	dstAddr netip.AddrPort // dst's UDP endpoint (from EndpointCache)
	udpConn *net.UDPConn  // ephemeral local socket
}

// SendUDP forwards a raw WireGuard payload to dst via UDP.
func (s *Session) SendUDP(payload []byte) error {
	dst := net.UDPAddrFromAddrPort(s.dstAddr)
	_, err := s.udpConn.WriteTo(payload, dst)
	return err
}

// Close releases the UDP socket.
func (s *Session) Close() {
	s.udpConn.Close()
}

// SessionTable manages all active relay sessions.
// Each session has an ephemeral UDP socket; a goroutine reads UDP replies
// and delivers them back to the src client as FrameRecvPacket.
type SessionTable struct {
	mu       sync.Mutex
	sessions map[sessionKey]*Session
}

func NewSessionTable() *SessionTable {
	return &SessionTable{
		sessions: make(map[sessionKey]*Session),
	}
}

// GetOrCreate returns an existing session or creates a new one.
// If created, starts a goroutine that reads UDP replies and calls onReply.
//
// onReply(srcKey, payload) is called for each UDP packet received from dst.
// The relay server passes its sendRecvPacket method here to inject the reply
// into src's TCP DERP connection as FrameRecvPacket(src=dstKey).
func (t *SessionTable) GetOrCreate(
	ctx context.Context,
	srcKey, dstKey key.NodePublic,
	dstAddr netip.AddrPort,
	onReply func(srcOfReply key.NodePublic, payload []byte),
) (*Session, error) {
	sk := sessionKey{src: srcKey, dst: dstKey}

	t.mu.Lock()
	if s, ok := t.sessions[sk]; ok {
		// Update dstAddr if endpoint changed (roaming).
		if s.dstAddr != dstAddr {
			log.Printf("session %v→%v: endpoint roamed %v→%v", fmtKey(srcKey), fmtKey(dstKey), s.dstAddr, dstAddr)
			s.dstAddr = dstAddr
		}
		t.mu.Unlock()
		return s, nil
	}

	// Create ephemeral UDP socket bound to any local port.
	udpConn, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
	if err != nil {
		t.mu.Unlock()
		return nil, fmt.Errorf("listen udp for session %v→%v: %w", fmtKey(srcKey), fmtKey(dstKey), err)
	}

	s := &Session{
		srcKey:  srcKey,
		dstKey:  dstKey,
		dstAddr: dstAddr,
		udpConn: udpConn,
	}
	t.sessions[sk] = s
	t.mu.Unlock()

	localAddr := udpConn.LocalAddr().String()
	log.Printf("session created: %v→%v via UDP %v→%v", fmtKey(srcKey), fmtKey(dstKey), localAddr, dstAddr)

	// Start reply reader goroutine.
	go t.readLoop(ctx, s, onReply)

	return s, nil
}

// readLoop reads UDP packets from dst and calls onReply for each.
// Stops when the UDP socket is closed or ctx is cancelled.
func (t *SessionTable) readLoop(ctx context.Context, s *Session, onReply func(key.NodePublic, []byte)) {
	buf := make([]byte, maxFrameSize)
	dstIP := s.dstAddr.Addr()

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		n, srcAddr, err := s.udpConn.ReadFromUDP(buf)
		if err != nil {
			// Socket closed (session removed) or network error.
			return
		}

		// Only accept packets from the expected destination IP.
		// Port may differ due to NAT roaming — that's OK.
		if fromIP := netip.MustParseAddr(srcAddr.IP.String()); fromIP != dstIP {
			log.Printf("session %v→%v: unexpected src %v (want %v), drop",
				fmtKey(s.srcKey), fmtKey(s.dstKey), srcAddr.IP, dstIP)
			continue
		}

		// Deliver to src client via the callback.
		// onReply wraps the payload as FrameRecvPacket(src=dstKey) on src's TCP conn.
		payload := make([]byte, n)
		copy(payload, buf[:n])
		onReply(s.dstKey, payload)
	}
}

// Remove closes and deletes a session.
func (t *SessionTable) Remove(srcKey, dstKey key.NodePublic) {
	sk := sessionKey{src: srcKey, dst: dstKey}
	t.mu.Lock()
	s, ok := t.sessions[sk]
	if ok {
		delete(t.sessions, sk)
	}
	t.mu.Unlock()
	if ok {
		s.Close()
		log.Printf("session removed: %v→%v", fmtKey(srcKey), fmtKey(dstKey))
	}
}

// RemoveAll closes all sessions for a given src (called when src disconnects).
func (t *SessionTable) RemoveAll(srcKey key.NodePublic) {
	t.mu.Lock()
	var toClose []*Session
	for sk, s := range t.sessions {
		if sk.src == srcKey {
			toClose = append(toClose, s)
			delete(t.sessions, sk)
		}
	}
	t.mu.Unlock()
	for _, s := range toClose {
		s.Close()
	}
	if len(toClose) > 0 {
		log.Printf("removed %d sessions for disconnected client %v", len(toClose), fmtKey(srcKey))
	}
}

func fmtKey(k key.NodePublic) string {
	s := k.String()
	if len(s) > 12 {
		return s[:12]
	}
	return s
}
