"""The workflows follow the repository's rules (design 10, CLAUDE.md)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def uses(path: Path) -> list[str]:
    found = []
    document = yaml.safe_load(path.read_text())
    for job in document["jobs"].values():
        found += [step["uses"] for step in job.get("steps", []) if "uses" in step]
    return found


def test_there_are_workflows() -> None:
    names = {p.name for p in WORKFLOWS}
    assert {
        "ci.yml",
        "release.yml",
        "deploy.yml",
        "terraform-pr.yml",
        "terraform-apply.yml",
    } <= names


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    for path in WORKFLOWS:
        for reference in uses(path):
            assert PINNED.match(reference), (
                f"{path.name}: {reference} is not pinned to a commit SHA"
            )


def test_every_pin_says_which_version_it_is() -> None:
    for path in WORKFLOWS:
        for line in path.read_text().splitlines():
            if "uses:" in line and "@" in line:
                assert re.search(r"# v\d", line), (
                    f"{path.name}: {line.strip()} has no version comment"
                )


def test_no_workflow_has_write_permissions_by_default() -> None:
    for path in WORKFLOWS:
        permissions = yaml.safe_load(path.read_text()).get("permissions")
        assert permissions == {"contents": "read"}, path.name


def test_aws_access_goes_through_oidc_and_an_environment_for_changes() -> None:
    for name in ("terraform-apply.yml", "deploy.yml"):
        document = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
        for job in document["jobs"].values():
            assert job["environment"] == "dev", name
            assert job["permissions"]["id-token"] == "write", name


def test_no_workflow_uploads_a_plan_file() -> None:
    for path in WORKFLOWS:
        text = path.read_text()
        for step in re.findall(r"upload-artifact[^\n]*\n(?:[^\n]*\n){0,6}", text):
            assert "tfplan" not in step and "plan" not in step.split("path:")[-1], path.name


def test_no_account_id_is_written_in_a_workflow_or_script() -> None:
    twelve_digits = re.compile(r"(?<![\d])\d{12}(?![\d])")
    for path in [
        *WORKFLOWS,
        *(ROOT / ".github" / "scripts").glob("*.sh"),
        *(ROOT / "scripts").glob("*.sh"),
    ]:
        for match in twelve_digits.findall(path.read_text()):
            assert match in {"000000000000", "123456789012"}, f"{path.name}: {match}"
