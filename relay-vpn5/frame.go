package main

import (
	"encoding/binary"
	"fmt"
	"io"
)

// DERP frame types (Tailscale protocol v2)
// Source: tailscale.com/derp/derp.go
const (
	frameServerKey     byte = 0x01 // S→C: magic[8] + serverPubKey[32]
	frameClientInfo    byte = 0x02 // C→S: clientPubKey[32] + nonce[24] + naclbox(json)
	frameServerInfo    byte = 0x03 // S→C: nonce[24] + naclbox(json)
	frameSendPacket    byte = 0x04 // C→S: destPubKey[32] + WireGuard payload
	frameRecvPacket    byte = 0x05 // S→C: srcPubKey[32] + WireGuard payload
	frameKeepAlive     byte = 0x06 // S→C: no payload — sent every ~60s
	frameNotePreferred byte = 0x07 // C→S: [1]byte preferred flag
	framePeerGone      byte = 0x08 // S→C: peerPubKey[32] + [1]byte reason
	framePing          byte = 0x12 // both: [8]byte data
	framePong          byte = 0x13 // both: [8]byte data (echo)
)

// derpMagic is the 8-byte prefix sent in FrameServerKey.
// "DERP" (4 bytes) + 🔑 U+1F511 (4 bytes UTF-8: F0 9F 94 91).
var derpMagic = []byte{0x44, 0x45, 0x52, 0x50, 0xf0, 0x9f, 0x94, 0x91}

const (
	protocolVersion = 2
	pubKeyLen       = 32
	nonceLen        = 24
	maxFrameSize    = 65535 + 64 // MaxPacketSize + DERP overhead
)

// readFrame reads one DERP frame.
// Returns frame type byte and payload (header stripped).
func readFrame(r io.Reader) (ft byte, payload []byte, err error) {
	var hdr [5]byte
	if _, err = io.ReadFull(r, hdr[:]); err != nil {
		return 0, nil, err
	}
	ft = hdr[0]
	frameLen := binary.BigEndian.Uint32(hdr[1:5])
	if frameLen > maxFrameSize {
		return 0, nil, fmt.Errorf("frame too large: %d", frameLen)
	}
	payload = make([]byte, frameLen)
	if _, err = io.ReadFull(r, payload); err != nil {
		return 0, nil, err
	}
	return ft, payload, nil
}

// writeFrame writes a DERP frame: 5-byte header + payload.
// Caller must flush any buffered writer afterwards.
func writeFrame(w io.Writer, ft byte, payload []byte) error {
	var hdr [5]byte
	hdr[0] = ft
	binary.BigEndian.PutUint32(hdr[1:], uint32(len(payload)))
	if _, err := w.Write(hdr[:]); err != nil {
		return err
	}
	if len(payload) > 0 {
		_, err := w.Write(payload)
		return err
	}
	return nil
}
