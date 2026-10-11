# Migration evidence

What was done to move traffic from legacy to modern, and what showed it was safe: one folder per
wave, written as each step happens. The procedure is the platform's
[`docs/runbooks/cutover.md`](https://github.com/loriamichaelj/shiptrack-platform/blob/dev/docs/runbooks/cutover.md);
the design is [`../DESIGN.md`](../DESIGN.md) §9.

| Folder | Wave |
|---|---|
| [`wave-0/`](wave-0/) | Dark launch: weights stay at 0, modern is proven correct and fast |
| `wave-1/` | Read path and UI, `track` 10, 50, 100 |
| `wave-2/` | Write path, `default` 10, 25, 50, 100 |
| `wave-3/` | Scheduled jobs and decommission |

## What goes in a wave folder

| File | Content |
|---|---|
| `README.md` | The wave's entry criteria and exit criteria, each with its result and a link to the run |
| `step-<n>.md` | One go/no-go record per weight step (template below) |
| `contract-<suite>.txt` | The pytest summary of each `validation.yml` contract run |
| `k6-<target>.txt` | The k6 summary lines of each baseline run |
| `gates-<step>.md` | The table printed by `cutover-gates.yml` |
| `findings.md` | The table printed by `security-findings.yml` |

The runs themselves are on GitHub and are linked, not copied. Only what a reader needs to check a
decision is stored here.

## Scrub before you commit

This repository is public. Evidence holds counts, ratios, seconds, alarm names, run links, and
public finding titles. It never holds an account ID, an ARN, an ALB or host address, an instance or
image identifier, the test-routing token, or a person's network address. The tools print numbers
only, and `scrub.yml` rejects a pull request that adds an account ID or an ALB name; read the diff
before you push anyway.

## Go/no-go record

Copy to `wave-N/step-<n>.md`.

```markdown
## Wave N, step X: <weights>

- Decision: go | hold | roll back
- Approved by: <person>
- Pull request: <link>
- Soak window: <start> to <end> (30 minutes)
- Load during the soak: k6-baseline, target none, run <link>
- Gates (cutover-gates run <link>): G2 <result>, G3 <result>, G4 <result>, G5 <result or n/a>
- G1 (validation.yml run <link>) and G6: <result>
- Alarms fired during the soak: <none | names>
- Notes: <anything a later reader needs>
```
