# Wave 1: read path and UI

Moves `GET /api/v1/track/*` and `GET /ui/*` together, `track` modern 10, 50, 100. The UI rule is
sticky, so a browser session stays on its stack. `default` stays at legacy 100, so every write goes
to legacy. Procedure: platform
[`cutover.md`](https://github.com/loriamichaelj/shiptrack-platform/blob/dev/docs/runbooks/cutover.md#wave-1-read-path-and-ui).

Entry: [wave 0](../wave-0/README.md) exit, with the accepted node-image findings of
[ADR-0021](../../ADR.md#adr-0021-accepted-node-image-findings-until-rebuilt-ami).

| Step | `track` | Result |
|---|---|---|
| [1a](step-1a.md) | legacy 90, modern 10 | Go |
| [1b](step-1b.md) | legacy 50, modern 50 | Go |
| [1c](step-1c.md) | legacy 0, modern 100 | Go |

## Exit

| Criterion | Result |
|---|---|
| Gates G1 to G4 pass at each step | Pass at 1a, 1b and 1c |
| UI stack badge shows `modern` for new sessions | Not looked at: the UI answers from modern, and the smoke contract checks the stack header on `/ui/` |
| Rollback available | `rollback-cutover.yml`, rehearsed with `dry_run` in wave 0 |

Wave 1 is complete: `GET /api/v1/track/*` and `GET /ui/*` are served by modern. Every write
still goes to legacy. Next: [wave 2](../wave-2/README.md), the write path, which moves the events
route that is 1.46 times legacy's at p95.

