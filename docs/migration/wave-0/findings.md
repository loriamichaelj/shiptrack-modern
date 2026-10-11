# Inspector findings

`check-security-findings.yml` on platform `8472048` (run
[38159470275](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38159470275)).
Findings are placed in a scope by resource tag (platform ADR-0029). Only `modern` is gated.

| Scope | Resource type | Distinct resources | Fixable CRITICAL or HIGH | All active |
|---|---|---|---|---|
| legacy | EC2 instance | 2 | 0 | 2 |
| modern | EC2 instance (EKS nodes) | 2 | **40** | 60 |
| modern | ECR image | 2 | 0 | 14 |
| other | EC2 instance | 2 | 42 | 63 |
| other | ECR image | 1 | 0 | 26 |

**Fixable CRITICAL or HIGH in modern: 40. The criterion is not met.**

The application images are clean. All 40 are Go modules compiled into the node's own binaries
(kubelet, containerd and their helpers) on the two EKS nodes, 20 on each:

| Severity | Title | Findings |
|---|---|---|
| HIGH | CVE-2026-39883 - go.opentelemetry.io/otel/sdk | 2 |
| HIGH | CVE-2026-46600 - golang.org/x/net | 2 |
| HIGH | CVE-2026-56851 - golang.org/x/text, golang.org/x/text and 2 more | 2 |
| HIGH | CVE-2026-56852 - golang.org/x/text | 2 |
| HIGH | CVE-2026-56854 - golang.org/x/crypto | 2 |
| HIGH | CVE-2026-56855 - golang.org/x/crypto | 2 |
| HIGH | CVE-2026-56866 - go/stdlib, go/stdlib and 23 more | 2 |
| HIGH | CVE-2026-73500 - go.etcd.io/etcd/client/pkg/v3 | 2 |
| HIGH | CVE-2026-78659 - go/stdlib, go/stdlib and 30 more | 2 |
| HIGH | CVE-2026-78660 - go/stdlib, go/stdlib and 30 more | 2 |
| HIGH | CVE-2026-78662 - golang.org/x/crypto | 2 |
| CRITICAL | CVE-2026-78663 - go/stdlib, go/stdlib and 30 more | 2 |
| HIGH | CVE-2026-78667 - go/stdlib, go/stdlib and 23 more | 2 |
| HIGH | CVE-2026-78669 - go/stdlib, go/stdlib and 30 more | 2 |
| HIGH | CVE-2026-84304 - google.golang.org/grpc | 2 |
| HIGH | CVE-2026-84445 - google.golang.org/grpc | 2 |
| HIGH | CVE-2026-94439 - go/stdlib, go/stdlib and 23 more | 2 |
| HIGH | CVE-2026-94440 - go/stdlib, go/stdlib and 23 more | 2 |
| HIGH | CVE-2026-97031 - go/stdlib, go/stdlib and 23 more | 2 |
| HIGH | GHSA-hrxh-6v49-42gf - google.golang.org/grpc | 2 |

The newest EKS AL2023 release when the nodes were created (2026-10-10) was v20261003, published
2026-10-08, so the nodes most likely run it already and a refresh would not clear these until AWS
ships a rebuilt image. The node group has no `release_version` pin yet; the release in use was not
read, because that needs AWS access.
