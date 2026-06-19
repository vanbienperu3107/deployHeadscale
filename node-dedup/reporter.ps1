# Tailnet reporter - chay tren moi node (ITOP, VOTAM, ...)
# POST netcheck (tailscale netcheck) len collector moi 60s.
#
# Cai dat:
#   1. Dat file nay vao bat ky thu muc nao, vd C:\scripts\reporter.ps1
#   2. Task Scheduler: Action = powershell.exe -NonInteractive -File C:\scripts\reporter.ps1
#      Trigger = At startup, repeat every 1 minute indefinitely
#
# Yeu cau:
#   - tailscale da join tailnet (co peer "collector" trong `tailscale status`)
#   - collector peer la vpn2 (IP tailnet 100.64.x.x), lang nghe cong 8090

param(
    [string]$CollectorUrl = "http://collector:8090",
    [int]$IntervalSeconds = 60
)

function Get-TailscaleNetcheck {
    # Chay tailscale netcheck va parse output thanh dict {code: ms}
    $output = & tailscale netcheck 2>&1 | Out-String
    $preferred = ""
    $latency = @{}

    foreach ($line in $output -split "`n") {
        # * Nearest DERP: VPN4 Vietnam
        if ($line -match '\* Nearest DERP:\s+(.+)') {
            $preferred = $matches[1].Trim()
        }
        # - vpn4-vn: 25.3ms  (VPN4 Vietnam)
        if ($line -match '-\s+([\w-]+):\s+([\d.]+)ms') {
            $latency[$matches[1]] = [double]$matches[2]
        }
        # - vpn3-vn:  (VPN3 Vietnam)  -- timeout, khong co ms
        elseif ($line -match '-\s+([\w-]+):\s+\(') {
            $latency[$matches[1]] = $null
        }
    }

    # Dich ten "Nearest DERP" (VPN4 Vietnam) -> code (vpn4-vn)
    # Cach don gian: preferred = key co latency nho nhat
    $prefCode = ""
    $minMs = [double]::MaxValue
    foreach ($kv in $latency.GetEnumerator()) {
        if ($null -ne $kv.Value -and $kv.Value -lt $minMs) {
            $minMs = $kv.Value
            $prefCode = $kv.Key
        }
    }

    return @{
        preferred_derp = $prefCode
        region_latency = $latency
    }
}

$hostname = $env:COMPUTERNAME.ToLower()

while ($true) {
    try {
        $nc = Get-TailscaleNetcheck
        $body = @{
            hostname       = $hostname
            preferred_derp = $nc.preferred_derp
            region_latency = $nc.region_latency
        }
        $json = $body | ConvertTo-Json -Depth 3

        $resp = Invoke-RestMethod -Method Post `
            -Uri "$CollectorUrl/metrics/netcheck" `
            -Body $json `
            -ContentType "application/json" `
            -TimeoutSec 10

        $codes = ($nc.region_latency.Keys | Sort-Object) -join ", "
        Write-Host "$(Get-Date -Format 'HH:mm:ss') OK preferred=$($nc.preferred_derp) regions=[$codes]"
    }
    catch {
        Write-Host "$(Get-Date -Format 'HH:mm:ss') ERR: $_"
    }

    Start-Sleep -Seconds $IntervalSeconds
}
