# Fork record

ShipTrack Modern starts as an unmodified import of the legacy application.

| | |
|---|---|
| Source repository | `shiptrack-legacy` (`https://github.com/loriamichaelj/shiptrack-legacy`) |
| Source tag | `v1.0.0` |
| Source commit | `061c33bdfa8573de22fc1e265cf86e73b1f46801` |

## Imported paths

`src/`, `migrations/`, `alembic.ini`, `tests/`, `web/`, `pyproject.toml`, `requirements.in`,
`requirements.txt`, `requirements-dev.in`, and `requirements-dev.txt`.

The commit that imports them is `4f23aea`, with no changes. To check it against the tag:

```sh
dest=$(mktemp -d) && mkdir "$dest/legacy" "$dest/modern"
paths="src migrations alembic.ini tests web pyproject.toml requirements.in requirements.txt requirements-dev.in requirements-dev.txt"
git -C ../shiptrack-legacy archive v1.0.0 $paths | tar -x -C "$dest/legacy"
git archive 4f23aea $paths | tar -x -C "$dest/modern"
diff -r "$dest/legacy" "$dest/modern"   # empty
```

Every later change to these paths arrives in a squash-merged pull request that names the
remediation it implements, for example `REM-06: carry events through SQS instead of an in-process
queue` (ADR-0016). The first of these, pull request #3 (`bf46f28`), carries M1 to M6 as one commit
whose body lists the eighteen commits it was built from. To read them one at a time:

```sh
git fetch origin refs/pull/3/head
git log --oneline 4f23aea..FETCH_HEAD
```

To see what a remediation changed on `dev`, diff the import commit against the current tree:

```sh
git diff --stat 4f23aea HEAD -- src migrations
git diff --stat 4f23aea HEAD -- web      # empty until Wave 2 completes: the UI source is frozen
```

The requirements files are replaced by `pyproject.toml` and `uv.lock` in the tooling change that
opens the application work (design 5.1). In `migrations/` only `env.py` changes, to take its
credentials from Secrets Manager (REM-01); revision `0001` is the same, so a database that legacy
created is a database modern can run against.

## Not imported

The legacy host runtime and deployment (`deploy/`, `scripts/`, `.github/`, `Makefile`,
`compose.yaml`) are specific to the EC2 stack and are replaced by the container image, the Helm
chart, and the modern workflows.
