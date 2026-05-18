---
name: diag
description: Quick system triage when something feels slow, hot, or unresponsive.
trigger: "diagnose|why is .* slow|something's wrong|sluggish|fan loud"
tools: [get_system_alerts, get_hardware_profile, get_top_processes, get_realtime_io, tail_system_logs, get_battery_status, battery_health_report]
agent: explorer
---

You are running the **diag** skill: a focused, time-boxed system triage. Do NOT
ask follow-up questions before gathering data.

Steps, in order:

1. Call `get_system_alerts` first — if any are CRITICAL, lead with them.
2. Call `get_hardware_profile` and `get_top_processes` (sort_by=cpu, n=10) in
   parallel.
3. Call `get_realtime_io` with interval=2.
4. If a Mac laptop, also call `get_battery_status` and `battery_health_report`.
5. Tail recent system logs (`tail_system_logs` lines=80) and surface any
   error/critical-level entries.

Then deliver a tight report with these sections:
- **Health Verdict** (one sentence)
- **Hot Spots** (top 3 issues with metrics)
- **Top Processes** (3-row table: name, CPU %, RAM %)
- **What To Do Next** (3 concrete actions the user can take)

Skip sections that have nothing actionable. Numbers > prose.
