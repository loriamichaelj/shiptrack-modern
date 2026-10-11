## Wave 2, step 2b: default 25% to modern

- Decision: go
- Approved by: the repository owner (the `dev` gate of the platform apply)
- Pull request: [platform #44](https://github.com/loriamichaelj/shiptrack-platform/pull/44), `default = { legacy = 75, modern = 25 }`, `track` unchanged at modern 100. Applied by run [38170054308](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38170054308), finished 19:56:54Z
- Evidence window: the 6 minutes before 20:03:30Z, all after the apply; legacy 895 requests, modern 5,652
- Load during the window: k6-baseline, target none, 5 minutes, 6,621 requests, 0.00% failed, run [38170199399](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38170199399)
- Gates (cutover-gates run [38170600609](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38170600609), wave 2): G2 PASS (legacy 0.00%, modern 0.00%), G3 PASS (legacy 16.0 ms, modern 16.2 ms), G4 PASS, G5 PASS (oldest message 0.0 s, events DLQ 0, notification DLQ 0)
- G1: contract-smoke against modern, run [38170163689](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38170163689), 8 passed. G6: unchanged since wave 0
- G-POD: `POD_GATE file_uris_older_than_5_minutes=0` at 19:59Z (legacy evidence run [38170154781](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38170154781))
- Alarms fired during the window: none. The SLA scan heartbeat is in ALARM by design with its actions off until wave 3
- Notes: the simulator ledger check is not yet run; it needs `ops-simulate-events.yml` with `target` set to `none`, which was added after this step (legacy #16), and runs at step 2c.
