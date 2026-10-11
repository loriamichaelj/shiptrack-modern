# Wave 2: write path

Moves everything the `track` and UI rules do not match, writes included: event ingestion, shipment
creation, proof-of-delivery upload. `default` modern 10, 25, 50, 100. `track` stays at modern 100.
Procedure: platform
[`cutover.md`](https://github.com/loriamichaelj/shiptrack-platform/blob/dev/docs/runbooks/cutover.md#wave-2-write-path).

## Entry

| Criterion | Result |
|---|---|
| Wave 1 at 100% | Yes, [wave 1](../wave-1/README.md) |
| Legacy v1.1.0 deployed | Yes, tag `v1.1.0` |
| `migrate_pod_to_s3.py` run on both hosts | Yes: 54 files moved, 0 failed, 0 checksum mismatches |
| PodSync cron installed | Yes, both hosts |
| G-POD = 0 | Yes: `file_uris_older_than_5_minutes=0` before and after step 2a |
| Legacy change freeze on | Declared by the owner; nothing was deployed to legacy during the wave |

| Step | `default` | Result |
|---|---|---|
| [2a](step-2a.md) | legacy 90, modern 10 | Go |
| [2b](step-2b.md) | legacy 75, modern 25 | Go |
| [2c](step-2c.md) | legacy 50, modern 50 | Go |
| [2d](step-2d.md) | legacy 0, modern 100 | Go |

## Exit

| Criterion | Result |
|---|---|
| G1 to G5 pass at each step | Pass at 2a, 2b, 2c and 2d, with G3 judged per route from 2d (platform ADR-0031) |
| DLQ = 0 | Yes: both DLQs 0 at every step |
| Simulator ledger shows 0 lost events for modern-routed traffic | Yes: 402 of 402 pinned to modern; 200 of 200 at 100% modern. The one event missing from the mixed run at 50% is most likely legacy's (AP-06), see step 2c |
| No `pod_not_migrated` for a POD older than 5 minutes | Yes: G-POD 0 at every step |

Wave 2 is complete: modern serves every request. Legacy is running and serves no traffic. Next:
handoff, then wave 3.

