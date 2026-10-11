# Gates over the two baselines

`cutover-gates.yml`, wave 1 table, 60-minute window that held both k6 baselines
(run [38160447671](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38160447671)).
Nothing was routed by weight: each baseline went to one stack by header.

| Gate | Result | Criterion | Measured |
|---|---|---|---|
| G1 Correctness | run validation.yml | contract suite passes with TARGET=modern | see `contract-full-modern.txt` |
| G6 UI parity | run validation.yml | ui_parity passes (before wave 1) | see `contract-ui-parity-modern.txt` |
| G2 Errors | PASS | modern 5xx ratio <= legacy + 0.5 pp | legacy 0.00%, modern 0.00% (requests 33238 and 39470) |
| G3 Latency | **FAIL** | modern p95 <= 1.2 x legacy p95 | legacy 14.2 ms, modern 18.1 ms (ratio 1.27) |
| G4 Stability | PASS | no SEV1 alarm, no pod restarts from the release | no SEV1 in ALARM; 0 SEV2 in ALARM; 1 with actions disabled, not counted |
| G5 Async health | n/a | judged from wave 2 | - |

The alarm with actions disabled is `shiptrack-modern-sla-scan-heartbeat`, created off until the
CronJob takes over in wave 3.

## G3

The gate reads the target group's `TargetResponseTime` p95 over the whole window: the time the
application took to answer. Across the mixed load (75% track, 15% events, 5% create, 5% UI) modern
was 18.1 ms against legacy's 14.2 ms, 1.27 times.

Separate k6 runs cannot say which route did it. The runner's distance to the load balancer changed
from run to run (the same route read 16 ms in one run and 87 ms in the next), so the baselines are
compared from one runner at the same time: k6 `TARGET=both` sends each iteration to one stack at
random (platform run
[38163777139](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38163777139), 10
minutes, 13,197 requests, 0.00% failed).

| Route | legacy p50 / p95 | modern p50 / p95 | modern over legacy, p50 / p95 |
|---|---|---|---|
| track (`GET /api/v1/track/{n}`) | 54.2 / 60.6 ms | 54.9 / 61.5 ms | 1.01 / 1.02 |
| event (`POST /api/v1/shipments/{id}/events`) | 53.4 / 58.9 ms | 61.6 / 88.9 ms | **1.15 / 1.51** |
| create (`POST /api/v1/shipments`) | 57.9 / 66.3 ms | 59.1 / 69.0 ms | 1.02 / 1.04 |
| ui_shell (`GET /ui/`) | 45.6 / 50.4 ms | 46.8 / 51.6 ms | 1.03 / 1.02 |
| ui_asset (`GET /ui/assets/{file}`) | 46.0 / 202.1 ms | 47.7 / 127.0 ms | 1.04 / 0.63 |

Times include the distance to the load balancer, which is common to both stacks in this run, so the
ratios are the comparison and the absolute numbers are not.

Only the event route is slower. `POST /events` sends to SQS before it answers `202`, because modern
never acknowledges an event it has not durably queued (REM-06); legacy's in-process queue (AP-06)
answers without leaving the process. That round trip is the cost of durability, and it falls on one
route in five.

Consequence for the waves: wave 1 moves `track` and `/ui/*` only, where the stacks are within 4%,
so G3 is expected to pass there. The event route moves in wave 2 with the rest of `default`; the
aggregate ratio there depends on the share of events, and is the figure to watch.
