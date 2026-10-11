# Handoff and wave 3: scheduled jobs and decommission

Procedure: platform
[`cutover.md`](https://github.com/loriamichaelj/shiptrack-platform/blob/dev/docs/runbooks/cutover.md#handoff-schema-ownership).
Legacy is kept running as a fallback and nothing is destroyed (platform ADR-0032, modern
[ADR-0023](../../ADR.md#adr-0023-contract-migration-not-taken)).

## Entry

[Wave 2](../wave-2/README.md) at 100% with G1 to G5 passing, and the simulator ledger complete.

## Handoff: schema ownership

| Step | Result | Evidence |
|---|---|---|
| Modern renders the migrate hook (`migrations.enabled: true`) | Done | [modern #29](https://github.com/loriamichaelj/shiptrack-modern/pull/29) |
| Deploy: the hook runs `alembic upgrade head`, a no-op at head | Helm revision 2, all three deployments rolled out, smoke 8 passed | modern deploy run [38175472937](https://github.com/loriamichaelj/shiptrack-modern/actions/runs/38175472937) |
| Legacy's `RUN_MIGRATIONS=false` | Not set; legacy is idle and has no deploy pending, so this is a safeguard and not a step | |

## Wave 3

| Step | Result | Evidence |
|---|---|---|
| 1. Remove legacy's crons | Sync cron and SLA cron removed on both hosts; `status` reads `sla=absent podsync=absent` on both | legacy runs [38175769559](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38175769559), [38176233513](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38176233513), [38176454187](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38176454187) |
| 2. Modern CronJob on, heartbeat alarm enabled | Applied and deployed | [modern #30](https://github.com/loriamichaelj/shiptrack-modern/pull/30), apply [38177119943](https://github.com/loriamichaelj/shiptrack-modern/actions/runs/38177119943), deploy [38177131864](https://github.com/loriamichaelj/shiptrack-modern/actions/runs/38177131864) |
| 3. Exactly one alert per breach | `contract-sla`: 3 overdue shipments flagged within 31 s and not touched again; then `SLA_DUPLICATES shipments=0 extra_alerts=0 alerts=3` | platform run [38178609695](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38178609695), legacy evidence run [38178711864](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38178711864) |
| 4. Contract migration | **Not taken** (ADR-0023) | |
| 5 and 6. Legacy scaled to zero and destroyed | **Not taken**: legacy keeps its hosts and target group, and its UI is on the preview port | platform [#48](https://github.com/loriamichaelj/shiptrack-platform/pull/48), ADR-0032 |

## Found and fixed during the wave

The heartbeat alarm paged SEV2 once its actions were on, although the scan was running. Its metric
filter matched a JSON field the log shipper's wrapper does not expose; it now matches the text
([modern #31](https://github.com/loriamichaelj/shiptrack-modern/pull/31)), applied at 22:10Z. The alarm
left ALARM: `check-cutover-gates` at 22:19Z reads 0 SEV2 in ALARM (run
[38179963457](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38179963457)).

## Exit

| Criterion | Result |
|---|---|
| Final cost snapshot captured | Not taken |
| Exactly one `sla_alerts` row per breached shipment | Yes: `alerts=3`, `extra_alerts=0` after three breaches |
| Legacy stays available as the fallback | Yes: running, idle, behind the preview port; `ops-rollback-cutover.yml` and `ops-legacy-cron.yml restore-sla` exist |
