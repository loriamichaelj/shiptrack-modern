"""The Terraform roots and the chart agree on names that no tool checks across files."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = re.compile(
    r'^\s*([\w-]+)\s*=\s*\{\s*namespace\s*=\s*([^,]+?),\s*name\s*=\s*"([^"]+)"\s*\}\s*$', re.M
)


def service_accounts(path: Path) -> dict[str, tuple[str, str]]:
    found = {}
    for key, namespace, name in ENTRY.findall(path.read_text()):
        found[key] = (namespace.strip().strip('"'), name)
    return found


def test_the_addons_service_accounts_are_the_ones_the_cluster_root_bound() -> None:
    cluster = service_accounts(ROOT / "terraform/cluster/data.tf")
    addons = service_accounts(ROOT / "terraform/addons/data.tf")
    assert addons, "the addons root declares no service accounts"
    for key, (namespace, name) in addons.items():
        bound = cluster[key]
        assert bound == (namespace, name), (
            f"{key}: bound to {bound}, installed as {(namespace, name)}"
        )


def test_the_workload_service_accounts_follow_the_chart_naming() -> None:
    cluster = service_accounts(ROOT / "terraform/cluster/data.tf")
    workloads = {
        k: v
        for k, v in cluster.items()
        if k in {"api", "worker-events", "worker-notify", "sla-scan", "migrate"}
    }
    assert set(workloads) == {"api", "worker-events", "worker-notify", "sla-scan", "migrate"}
    for key, (namespace, name) in workloads.items():
        assert name == f"shiptrack-{key}"
        assert namespace == "local.namespace"
