## Wave 1, step 1a: track 10% to modern

- Decision: go
- Approved by: the repository owner (the `dev` gate of the platform apply)
- Pull request: [platform #39](https://github.com/loriamichaelj/shiptrack-platform/pull/39), `track = { legacy = 90, modern = 10 }`, `default` unchanged. Applied by run [38165515940](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38165515940), finished 18:52:02Z
- Evidence window: the 20 minutes before 19:03:49Z, which start 8 minutes before the apply; legacy 11,606 requests, modern 1,027
- Load during the window: k6-baseline, target none, 10 minutes, 13,221 requests, 0.00% failed, run [38165689796](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38165689796)
- Gates (cutover-gates run [38166426217](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38166426217)): G2 PASS (legacy 0.00%, modern 0.00%), G3 PASS (legacy 13.3 ms, modern 15.4 ms, ratio 1.16), G4 PASS, G5 n/a
- G1 (contract-smoke against modern, run [38165653685](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38165653685)): 8 passed. G6: passed in wave 0 and is a property of the two builds, which have not changed
- Alarms fired during the window: none. The SLA scan heartbeat is in ALARM by design and has its actions off until wave 3
- Notes: modern took 1,027 of the 12,633 requests in the window, which is the 10% of track and UI after the apply, diluted by the minutes before it. The G3 ratio of 1.16 is under the 1.2 limit with 0.04 of headroom; the same-runner comparison (wave 0) had these routes within 4%, so the 2 ms gap is expected. G3 is the number to watch at 50%.
