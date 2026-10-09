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

The first commit on `dev` that contains them is the import itself, with no changes. To check:

```sh
dest=$(mktemp -d)
git -C ../shiptrack-legacy archive v1.0.0 src migrations alembic.ini tests web pyproject.toml \
  requirements.in requirements.txt requirements-dev.in requirements-dev.txt | tar -x -C "$dest"
diff -r "$dest/src" src   # empty until the first refactor commit
```

Every later change to these paths is a refactor commit that names the remediation it implements,
for example `REM-06: replace the in-process queue with SQS`.

## Not imported

The legacy host runtime and deployment (`deploy/`, `scripts/`, `.github/`, `Makefile`,
`compose.yaml`) are specific to the EC2 stack and are replaced by the container image, the Helm
chart, and the modern workflows.
