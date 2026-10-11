# Wave 0: dark launch

Modern is deployed and serving, and every weight is 0, so no user request reaches it. The wave
proves modern correct and fast before any traffic moves, and stores the baseline the later gates
compare against. Procedure: platform
[`cutover.md`](https://github.com/loriamichaelj/shiptrack-platform/blob/dev/docs/runbooks/cutover.md#wave-0-dark-launch-weights-stay-0).

**Status: open. The security criterion is not met (40 fixable findings on modern's EKS nodes).**

## Entry

| Criterion | Result |
|---|---|
| Platform applied | Yes |
| Modern cluster, add-ons and release deployed | Yes; the smoke through the ALB passes with `X-ShipTrack-Stack: modern` |
| `cutover.md` and the controls it names exist | Yes (platform ADR-0028) |

## Exit

| Criterion | Result | Evidence |
|---|---|---|
| Contract suite passes against modern (G1) | **Pass**, 53 passed | [`contract-full-modern.txt`](contract-full-modern.txt), run [38155704412](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155704412) |
| Same suite passes against legacy | Pass, 53 passed: the contract describes both stacks | [`contract-full-legacy.txt`](contract-full-legacy.txt), run [38155800708](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155800708) |
| UI build parity (G6) | **Pass** | [`contract-ui-parity-modern.txt`](contract-ui-parity-modern.txt), run [38155769590](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155769590) |
| k6 thresholds met on both stacks (`http_req_failed` < 1%, `p(95)` < 500 ms) | **Pass**: 0.00% failed; p95 50.4 ms legacy and 52.4 ms modern | [`k6-legacy.txt`](k6-legacy.txt) run [38155855171](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38155855171); [`k6-modern.txt`](k6-modern.txt) run [38157975440](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38157975440) |
| No fixable CRITICAL or HIGH in modern | **Not met**: 40 on the two EKS nodes, 0 in the images | [`findings.md`](findings.md), run [38159470275](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38159470275) |
| Alarms in `OK`, dashboard shows both target groups | Alarms: no SEV1, no SEV2 in ALARM; one alarm is off by design. Dashboard not looked at | [`gates-baseline.md`](gates-baseline.md) |
| Evidence stored here | This folder | |

## Known before wave 1

- **G3 would fail.** Modern's target-side p95 is 18.1 ms against legacy's 14.2 ms at the same load,
  1.27 times, over the 1.2 limit. The absolute gap is 4 ms and k6 sees 2 ms from outside. Cause not
  yet investigated; see [`gates-baseline.md`](gates-baseline.md).
- **The node findings need a rebuilt node image.** [`findings.md`](findings.md) has the table.
- The two baselines ran on different platform commits (legacy on `0dc6c37`, modern on `1685ed1`);
  the k6 scenario did not change between them.

## Decision

Hold. Wave 0 is not closed, and wave 1 does not start, until the findings criterion passes or
the gap is recorded as an accepted risk in an ADR with the person who accepts it named.
