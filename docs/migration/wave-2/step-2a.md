## Wave 2, step 2a: default 10% to modern

- Decision: go
- Approved by: the repository owner (the `dev` gate of the platform apply)
- Pull request: [platform #43](https://github.com/loriamichaelj/shiptrack-platform/pull/43), `default = { legacy = 90, modern = 10 }`, `track` unchanged at modern 100. Applied by run [38169168617](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38169168617), finished 19:45:13Z
- Evidence window: the 8 minutes before 19:51:09Z, all after the apply; legacy 910 requests, modern 4,595 (modern carries every read, legacy every write that is not on modern's 10%)
- Load during the window: k6-baseline, target none, 5 minutes, 6,660 requests, 0.00% failed, run [38169383587](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38169383587)
- Gates (cutover-gates run [38169755694](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38169755694), wave 2): G2 PASS (legacy 0.00%, modern 0.00%), G3 PASS (legacy 14.6 ms, modern 13.1 ms), G4 PASS, G5 PASS (oldest message 0.0 s, events DLQ 0, notification DLQ 0)
- G1: contract-smoke against modern, run [38169359583](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38169359583), 8 passed; contract-full against modern, run [38169810877](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38169810877), 53 passed, which includes uploading a proof of delivery and reading it back. G6: unchanged since wave 0
- G-POD: `POD_GATE file_uris_older_than_5_minutes=0` at 19:46:59Z, after the apply (legacy evidence run [38169362622](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38169362622))
- Alarms fired during the window: none. The SLA scan heartbeat is in ALARM by design with its actions off until wave 3
- Not yet checked: the simulator ledger for modern-routed traffic ("0 lost events"). It is run before the step that reaches 100%.
- Notes: the target-group G3 compares legacy's mixed writes with modern's reads plus 10% of writes, so it is not like for like; the same-runner comparison for the event route is 1.14 at p50 and 1.46 at p95 (wave 1, step 1c).
