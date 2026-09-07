// derpdial do THOI GIAN BAT TAY DERP toi mot derper.
//
// Vi sao can no: verify-clients chay BEN TRONG duong bat tay
// (derp/derpserver/derpserver.go:1532, goi tu duong accept), voi timeout 5s.
// Bat --verify-client-url tren vpn4 nghia la moi ket noi DERP moi phai cho mot
// vong HTTP tu Peru ve headscale o VN. Cong cu nay do chinh cai do.
//
// Cach dung (do TRUOC va SAU khi bat co, roi so sanh):
//
//	derpdial -host vpn4.hangocthanh.io.vn -n 10
//
// Luu y ve cach doc so:
//   - TRUOC khi bat co: relay dang mo -> nodekey ngau nhien bat tay THANH CONG.
//     So do duoc = TLS + bat tay DERP thuan.
//   - SAU khi bat co: nodekey ngau nhien khong co trong tailnet -> bi TU CHOI.
//     So do duoc = TLS + bat tay + MOT VONG verify ve headscale.
//     Bi tu choi la DUNG - no chung minh cai cong dang hoat dong.
//   - Hieu hai so = chi phi verify ma MOI client hop le cung phai tra.
//
// Cong cu nay khong can nodekey that va khong sua gi tren server.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"sort"
	"time"

	"tailscale.com/derp/derphttp"
	"tailscale.com/net/netmon"
	"tailscale.com/types/key"
)

func main() {
	host := flag.String("host", "", "hostname cua derper, vd vpn4.hangocthanh.io.vn")
	n := flag.Int("n", 10, "so lan do")
	timeout := flag.Duration("timeout", 20*time.Second, "timeout moi lan do")
	flag.Parse()

	if *host == "" {
		fmt.Fprintln(os.Stderr, "thieu -host")
		os.Exit(2)
	}

	// NewStatic: anh chup mot lan trang thai mang, khong theo doi thay doi.
	// Dung cho CLI ngan han dung nhu doc netmon khuyen (netmon.go:403) —
	// netmon.New() doi mot eventbus, thua cho viec nay.
	netMon := netmon.NewStatic()

	url := "https://" + *host + "/derp"
	fmt.Printf("derper : %s\n", url)
	fmt.Printf("so lan : %d\n\n", *n)

	var okDur []time.Duration
	var failDur []time.Duration
	var lastErr string

	for i := 1; i <= *n; i++ {
		// Moi lan mot nodekey MOI: derper khong duoc phep tra loi tu cache.
		priv := key.NewNode()
		c, err := derphttp.NewClient(priv, url, func(string, ...any) {}, netMon)
		if err != nil {
			fmt.Fprintf(os.Stderr, "NewClient: %v\n", err)
			os.Exit(1)
		}

		ctx, cancel := context.WithTimeout(context.Background(), *timeout)
		start := time.Now()
		err = c.Connect(ctx)
		d := time.Since(start)
		cancel()
		c.Close()

		if err != nil {
			failDur = append(failDur, d)
			lastErr = err.Error()
			fmt.Printf("  %2d  %7.1f ms  TU CHOI/LOI  %v\n", i, ms(d), err)
		} else {
			okDur = append(okDur, d)
			fmt.Printf("  %2d  %7.1f ms  OK\n", i, ms(d))
		}
		time.Sleep(300 * time.Millisecond)
	}

	fmt.Printf("\n%s\n", "----------------------------------------")
	report("bat tay THANH CONG", okDur)
	report("bat tay BI TU CHOI/LOI", failDur)
	if lastErr != "" {
		fmt.Printf("\nloi cuoi: %s\n", lastErr)
	}

	// Khong exit != 0 khi bi tu choi: sau khi bat co thi TU CHOI la ket qua
	// DUNG. Job goi cong cu nay tu quyet dinh y nghia.
}

func ms(d time.Duration) float64 { return float64(d.Microseconds()) / 1000.0 }

func report(label string, ds []time.Duration) {
	if len(ds) == 0 {
		fmt.Printf("%-24s  (khong co)\n", label)
		return
	}
	sort.Slice(ds, func(i, j int) bool { return ds[i] < ds[j] })
	sum := time.Duration(0)
	for _, d := range ds {
		sum += d
	}
	fmt.Printf("%-24s  n=%d  min=%.1f  p50=%.1f  max=%.1f  tb=%.1f  (ms)\n",
		label, len(ds),
		ms(ds[0]), ms(ds[len(ds)/2]), ms(ds[len(ds)-1]), ms(sum/time.Duration(len(ds))))
}
