## Wave 1, step 1c: track 100% to modern

- Decision: go
- Approved by: the repository owner (the `dev` gate of the platform apply)
- Pull request: [platform #42](https://github.com/loriamichaelj/shiptrack-platform/pull/42), `track = { legacy = 0, modern = 100 }`, `default` unchanged. Applied by run [38167682908](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38167682908), finished 19:24:21Z
- Evidence window: the 12 minutes before 19:36:03Z, all after the apply; legacy 4,187 requests (writes only), modern 8,300
- Load during the window: k6-baseline, target none, 5 minutes, 6,585 requests, 0.00% failed, run [38167938939](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38167938939)
- Gates (cutover-gates run [38168713974](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38168713974)): G2 PASS (legacy 0.00%, modern 0.00%), G3 PASS (legacy 14.1 ms, modern 16.3 ms, ratio 1.16), G4 PASS, G5 n/a
- G1 (contract-smoke against modern, run [38167900792](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38167900792)): 8 passed. G6: unchanged since wave 0
- Alarms fired during the window: none. The SLA scan heartbeat is in ALARM by design with its actions off until wave 3
- Like-for-like comparison (k6 `TARGET=both`, one runner, 5 minutes, 6,569 requests, 0.00% failed, run [38168324740](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38168324740)): modern over legacy at p50 / p95 is track 1.01 / 1.02, create 1.02 / 0.95, UI shell 1.03 / 1.02, UI asset 1.05 / 1.01, and event **1.14 / 1.46**
- Notes: at 100% the two target groups carry different traffic: modern serves every read and legacy every write, so the G2 and G3 rows are not like for like, and the `both` run is the comparison. Its event row repeats wave 0's (1.15 / 1.51): `POST /events` waits for SQS before answering (REM-06). The event route moves in wave 2, where the aggregate G3 on the target group is the number to watch.
