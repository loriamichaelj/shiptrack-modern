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

The gate reads the target group's `TargetResponseTime` p95 over the whole window, which is the time
the application took to answer. k6 measures from the runner through the load balancer, and there the
two stacks are 50.4 and 52.4 ms. So modern answers about 4 ms slower at the target, 27% over legacy,
and the network and load balancer hide most of it from the client. At weight 0 this is the baseline,
not a failed step, but G3 at wave 1 will fail the same way unless it moves.
