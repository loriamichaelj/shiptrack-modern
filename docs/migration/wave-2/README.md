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
