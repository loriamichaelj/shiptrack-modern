## Wave 1, step 1b: track 50% to modern

- Decision: go
- Approved by: the repository owner (the `dev` gate of the platform apply)
- Pull request: [platform #41](https://github.com/loriamichaelj/shiptrack-platform/pull/41), `track = { legacy = 50, modern = 50 }`, `default` unchanged. Applied by run [38166665901](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38166665901), finished 19:11:48Z
- Evidence window: the 7 minutes before 19:18:01Z, all after the apply; legacy 3,278 requests, modern 2,208
- Load during the window: k6-baseline, target none, 5 minutes, 6,659 requests, 0.02% failed, run [38167044861](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38167044861)
- Gates (cutover-gates run [38167426475](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38167426475)): G2 PASS (legacy 0.00%, modern 0.00%), G3 PASS (legacy 14.1 ms, modern 13.3 ms, ratio 0.94), G4 PASS, G5 n/a
- G1 (contract-smoke against modern, run [38167007520](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38167007520)): 8 passed. G6: unchanged since wave 0
- Alarms fired during the window: none. The SLA scan heartbeat is in ALARM by design with its actions off until wave 3
- Notes: k6 counted 0.02% failed (one or two of 6,659 requests). Both target groups report 0.00% 5xx and the load balancer's own 5xx alarm did not fire, so it was not a 5xx from a target; it is under the 1% threshold, and the cause was not isolated. Modern's p95 at the target is below legacy's at this weight.
