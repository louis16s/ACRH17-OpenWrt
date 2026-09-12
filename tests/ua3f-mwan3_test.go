//go:build linux

package nfqueue

import (
	"encoding/binary"
	nfq "github.com/florianl/go-nfqueue/v2"
	"github.com/mdlayher/netlink"
	"github.com/sunbk201/ua3f/internal/common"
	"testing"
)

func TestMwan3ConnmarkPreserved(t *testing.T) {
	s := &Server{SniffCtMarkLower: 10201, SniffCtMarkUpper: 10216, HTTPCtMark: 202, NotHTTPCtMark: 201}
	for _, high := range []uint32{0, 0x01000000, 0x02000000, 0x3f000000} {
		for _, tc := range []struct {
			name   string
			low    uint32
			result common.RewriteDecision
			set    bool
			want   uint32
		}{
			{"new", 0, common.RewriteDecision{}, true, 10201},
			{"sniff", 10201, common.RewriteDecision{}, true, 10202},
			{"skip", 0, common.RewriteDecision{NeedSkip: true}, true, 201},
			{"cached", 10201, common.RewriteDecision{NeedCache: true}, true, 201},
			{"modified", 10201, common.RewriteDecision{Modified: true}, true, 202},
			{"known-http", 202, common.RewriteDecision{}, false, 0},
			{"known-non-http", 201, common.RewriteDecision{}, false, 0},
		} {
			mark := make([]byte, 4)
			binary.BigEndian.PutUint32(mark, high|tc.low)
			ct, err := netlink.MarshalAttributes([]netlink.Attribute{{Type: 8, Data: mark}})
			if err != nil {
				t.Fatal(err)
			}
			packet := &common.Packet{A: &nfq.Attribute{Ct: &ct}}
			set, got := s.getNextMark(packet, &tc.result)
			want := tc.want
			if tc.set {
				want |= high
			}
			if set != tc.set || got != want {
				t.Errorf("%s high=%#x: got (%t,%#x), want (%t,%#x)", tc.name, high, set, got, tc.set, want)
			}
		}
	}
}
