package main

import (
	"bufio"
	"context"
	"encoding/json"
	"log"
	"net"
	"net/http"
	"sync"
	"time"

	"go4.org/mem"
	"tailscale.com/types/key"
)

// clientInfo is the JSON payload inside FrameClientInfo (sent by Tailscale clients).
type clientInfo struct {
	Version     int    `json:"version,omitempty"`
	MeshKey     string `json:"meshKey,omitempty"`
	CanAckPings bool   `json:"CanAckPings,omitempty"`
	IsProber    bool   `json:"IsProber,omitempty"`
}

// serverInfo is the JSON payload the server sends back in FrameServerInfo.
type serverInfo struct {
	Version int `json:"version,omitempty"`
}

// clientConn represents one connected DERP client (e.g., ITOPS).
type clientConn struct {
	pubKey key.NodePublic
	conn   net.Conn
	bw     *bufio.Writer
	wmu    sync.Mutex // serialises writes to bw
}

// sendFrame writes a DERP frame to this client and flushes.
func (cc *clientConn) sendFrame(ft byte, payload []byte) error {
	cc.wmu.Lock()
	defer cc.wmu.Unlock()
	if err := writeFrame(cc.bw, ft, payload); err != nil {
		return err
	}
	return cc.bw.Flush()
}

// sendRecvPacket delivers FrameRecvPacket(src=srcKey, payload) to this client.
// Used both for locally-routed packets and UDP-received replies.
func (cc *clientConn) sendRecvPacket(srcKey key.NodePublic, payload []byte) error {
	frame := make([]byte, pubKeyLen+len(payload))
	copy(frame[:pubKeyLen], srcKey.AppendTo(nil))
	copy(frame[pubKeyLen:], payload)
	return cc.sendFrame(frameRecvPacket, frame)
}

// Server is the hybrid DERP server.
// It speaks the DERP protocol to TCP clients and routes packets:
//   - To another TCP-connected client  → writes FrameRecvPacket on their TCP conn
//   - To a UDP-capable peer            → sends raw WireGuard payload via UDP
type Server struct {
	privateKey key.NodePrivate
	publicKey  key.NodePublic
	endpoint   *EndpointCache
	sessions   *SessionTable

	mu      sync.RWMutex
	clients map[key.NodePublic]*clientConn
}

func NewServer(priv key.NodePrivate, ep *EndpointCache, st *SessionTable) *Server {
	return &Server{
		privateKey: priv,
		publicKey:  priv.Public(),
		endpoint:   ep,
		sessions:   st,
		clients:    make(map[key.NodePublic]*clientConn),
	}
}

// Handler returns an http.Handler that upgrades connections to DERP.
func (s *Server) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Health probe for CI/CD and load balancers.
		if r.URL.Path == "/derp/probe" || r.URL.Path == "/relay/probe" {
			w.Header().Set("Content-Type", "text/plain")
			w.WriteHeader(http.StatusOK)
			w.Write([]byte("OK"))
			return
		}

		if r.Header.Get("Upgrade") != "DERP" {
			http.Error(w, "DERP upgrade required", http.StatusUpgradeRequired)
			return
		}

		hj, ok := w.(http.Hijacker)
		if !ok {
			http.Error(w, "hijacking not supported", http.StatusInternalServerError)
			return
		}
		conn, brw, err := hj.Hijack()
		if err != nil {
			log.Printf("hijack: %v", err)
			return
		}

		// Tailscale v1.86+ clients send DERP-Fast-Start: 1 which skips HTTP 101.
		if r.Header.Get("DERP-Fast-Start") != "1" {
			conn.Write([]byte("HTTP/1.1 101 Switching Protocols\r\n" +
				"Upgrade: DERP\r\nConnection: Upgrade\r\n\r\n"))
		}

		s.handleConn(r.Context(), conn, brw)
	})
}

// handleConn runs the DERP protocol for one client connection.
func (s *Server) handleConn(ctx context.Context, conn net.Conn, brw *bufio.ReadWriter) {
	defer conn.Close()
	remoteAddr := conn.RemoteAddr().String()

	// ── Step 1: Send FrameServerKey ──────────────────────────────────────────
	keyMsg := make([]byte, 0, len(derpMagic)+pubKeyLen)
	keyMsg = append(keyMsg, derpMagic...)
	keyMsg = s.publicKey.AppendTo(keyMsg)
	if err := writeFrame(brw.Writer, frameServerKey, keyMsg); err != nil {
		return
	}
	if err := brw.Writer.Flush(); err != nil {
		return
	}

	// ── Step 2: Read FrameClientInfo (10s deadline) ──────────────────────────
	conn.SetReadDeadline(time.Now().Add(10 * time.Second))
	ft, payload, err := readFrame(brw.Reader)
	conn.SetReadDeadline(time.Time{})
	if err != nil || ft != frameClientInfo {
		log.Printf("%s: expected FrameClientInfo, got type=0x%02x err=%v", remoteAddr, ft, err)
		return
	}
	if len(payload) < pubKeyLen {
		log.Printf("%s: FrameClientInfo payload too short (%d bytes)", remoteAddr, len(payload))
		return
	}

	clientKey := key.NodePublicFromRaw32(mem.B(payload[:pubKeyLen]))
	sealed := payload[pubKeyLen:]

	// Verify the NaCl box proves the client owns clientKey.
	_, ok := s.privateKey.OpenFrom(clientKey, sealed)
	if !ok {
		log.Printf("%s: FrameClientInfo NaCl verify failed (key=%v)", remoteAddr, fmtKey(clientKey))
		return
	}

	// ── Step 3: Send FrameServerInfo ─────────────────────────────────────────
	infoJSON, _ := json.Marshal(serverInfo{Version: protocolVersion})
	sealedInfo := s.privateKey.SealTo(clientKey, infoJSON)
	if err := writeFrame(brw.Writer, frameServerInfo, sealedInfo); err != nil {
		return
	}
	if err := brw.Writer.Flush(); err != nil {
		return
	}

	// ── Register client ───────────────────────────────────────────────────────
	cc := &clientConn{pubKey: clientKey, conn: conn, bw: brw.Writer}
	s.mu.Lock()
	s.clients[clientKey] = cc
	s.mu.Unlock()
	log.Printf("connected: %v from %v", fmtKey(clientKey), remoteAddr)

	defer func() {
		s.mu.Lock()
		delete(s.clients, clientKey)
		s.mu.Unlock()
		s.sessions.RemoveAll(clientKey)
		log.Printf("disconnected: %v", fmtKey(clientKey))
	}()

	// ── Main loop ─────────────────────────────────────────────────────────────
	kaTicker := time.NewTicker(60 * time.Second)
	defer kaTicker.Stop()

	// Read frames in a goroutine so keepalive ticks can fire concurrently.
	type inFrame struct {
		ft      byte
		payload []byte
		err     error
	}
	frameCh := make(chan inFrame, 32)
	go func() {
		for {
			ft, payload, err := readFrame(brw.Reader)
			frameCh <- inFrame{ft, payload, err}
			if err != nil {
				return
			}
		}
	}()

	for {
		select {
		case <-ctx.Done():
			return

		case <-kaTicker.C:
			if err := cc.sendFrame(frameKeepAlive, nil); err != nil {
				return
			}

		case msg := <-frameCh:
			if msg.err != nil {
				return // connection closed or read error
			}
			s.dispatch(ctx, cc, msg.ft, msg.payload)
		}
	}
}

// dispatch handles one incoming frame from a connected client.
func (s *Server) dispatch(ctx context.Context, src *clientConn, ft byte, payload []byte) {
	switch ft {

	case frameSendPacket:
		// payload = destPubKey[32] + WireGuard bytes
		if len(payload) < pubKeyLen {
			return
		}
		destKey := key.NodePublicFromRaw32(mem.B(payload[:pubKeyLen]))
		wgData := payload[pubKeyLen:]
		s.route(ctx, src, destKey, wgData)

	case framePing:
		// Must echo back as FramePong.
		if len(payload) == 8 {
			src.sendFrame(framePong, payload)
		}

	case frameNotePreferred:
		// Client signals preferred relay — informational, no action needed.

	default:
		// Unknown frame types: ignore (forward-compat).
	}
}

// route decides how to deliver a WireGuard payload to destKey.
//
// Decision tree (both checks happen on EVERY packet):
//
//  1. destKey is connected here via TCP DERP
//     → write FrameRecvPacket directly on their TCP conn  (zero-hop, fastest)
//
//  2. destKey has a UDP endpoint (from sidecar cache)
//     → send raw WireGuard payload via ephemeral UDP socket
//       · reply arrives on that socket → goroutine calls src.sendRecvPacket()
//
//  3. Neither → drop (log warning)
//     This shouldn't happen in normal operation; Tailscale clients only contact
//     DERP servers they believe can reach the destination.
func (s *Server) route(ctx context.Context, src *clientConn, destKey key.NodePublic, wgData []byte) {
	// Option 1: dest is connected locally (e.g., votam also connected here via TCP).
	s.mu.RLock()
	destCC, locallyConnected := s.clients[destKey]
	s.mu.RUnlock()

	if locallyConnected {
		if err := destCC.sendRecvPacket(src.pubKey, wgData); err != nil {
			log.Printf("local route %v→%v: %v", fmtKey(src.pubKey), fmtKey(destKey), err)
		}
		return
	}

	// Option 2: dest has a UDP endpoint → relay via UDP.
	udpAddr, hasUDP := s.endpoint.Resolve(ctx, destKey)
	if !hasUDP {
		log.Printf("drop %v→%v: no path (not connected, no UDP endpoint)", fmtKey(src.pubKey), fmtKey(destKey))
		return
	}

	// onReply is called by the session's readLoop for each UDP packet from destKey.
	// It injects the reply into src's TCP DERP stream as FrameRecvPacket(src=destKey).
	onReply := func(replyFromKey key.NodePublic, reply []byte) {
		if err := src.sendRecvPacket(replyFromKey, reply); err != nil {
			log.Printf("reply inject %v→%v: %v", fmtKey(replyFromKey), fmtKey(src.pubKey), err)
		}
	}

	sess, err := s.sessions.GetOrCreate(ctx, src.pubKey, destKey, udpAddr, onReply)
	if err != nil {
		log.Printf("session create %v→%v: %v", fmtKey(src.pubKey), fmtKey(destKey), err)
		return
	}

	if err := sess.SendUDP(wgData); err != nil {
		log.Printf("udp send %v→%v: %v — invalidating endpoint", fmtKey(src.pubKey), fmtKey(destKey), err)
		s.endpoint.Invalidate(destKey)
		s.sessions.Remove(src.pubKey, destKey)
	}
}
