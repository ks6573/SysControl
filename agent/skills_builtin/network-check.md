---
name: network-check
description: Diagnose internet connectivity, latency, and bandwidth issues.
trigger: "internet slow|wifi (broken|down|spotty)|why is .* loading slow"
tools: [network_latency_check, get_realtime_io, get_network_usage, get_network_connections, get_wifi_networks]
---

You are running the **network-check** skill. Goal: tell the user in 60 seconds
whether the issue is the local link, the ISP path, or DNS.

Steps:

1. In parallel:
   - `network_latency_check(host='1.1.1.1')` — raw IP, bypasses DNS.
   - `network_latency_check(host='google.com')` — DNS path.
   - `get_realtime_io(interval=2)` — actual throughput right now.
2. `get_wifi_networks` — note SNR / RSSI of the connected network.
3. `get_network_connections` — flag if anything else is hammering the link
   (top-by-bytes processes).

Report layout:

- **Verdict** — one of: link OK, DNS slow, ISP path slow, link saturated.
- **Latency** — table (1.1.1.1 ms, google.com ms, packet loss).
- **Throughput** — current MB/s down + up.
- **Wi-Fi** — SSID + signal quality.
- **Hogs** — any process pushing > 1 MB/s.
- **Recommended Fix** — one concrete action.

If everything looks fine, say so plainly — don't manufacture a problem.
