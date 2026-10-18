"""The rendered chart carries the properties the design requires (7.2 to 7.4)."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts" / "shiptrack"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def render(*extra: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "helm", "template", "shiptrack", str(CHART),
            "-f", str(CHART / "ci-values.yaml"),
            "-f", str(CHART / "values-dev.yaml"),
            *extra,
        ],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def render_gcp(*extra: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "helm", "template", "shiptrack", str(CHART),
            "-f", str(CHART / "ci-values-gcp.yaml"),
            *extra,
        ],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def by_kind(docs: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {d["metadata"]["name"]: d for d in docs if d["kind"] == kind}


def pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    template = doc["spec"].get("template") or doc["spec"]["jobTemplate"]["spec"]["template"]
    return template["spec"]


def pods() -> dict[str, dict[str, Any]]:
    docs = render("--set", "migrations.enabled=true")
    out = {name: pod_spec(d) for name, d in by_kind(docs, "Deployment").items()}
    out["shiptrack-sla-scan"] = pod_spec(by_kind(docs, "CronJob")["shiptrack-sla-scan"])
    out["shiptrack-migrate"] = pod_spec(by_kind(docs, "Job")["shiptrack-migrate"])
    return out


def test_every_workload_is_non_root_read_only_and_drops_capabilities() -> None:
    for name, spec in pods().items():
        assert spec["securityContext"]["runAsNonRoot"] is True, name
        assert spec["securityContext"]["runAsUser"] == 10001, name
        assert spec["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}, name
        for container in spec["containers"]:
            context = container["securityContext"]
            assert context["allowPrivilegeEscalation"] is False, name
            assert context["readOnlyRootFilesystem"] is True, name
            assert context["capabilities"] == {"drop": ["ALL"]}, name


def test_images_are_referenced_by_digest() -> None:
    for name, spec in pods().items():
        for container in spec["containers"]:
            assert "@sha256:" in container["image"], name


def test_there_are_memory_limits_and_no_cpu_limits() -> None:
    for name, spec in pods().items():
        resources = spec["containers"][0]["resources"]
        assert "memory" in resources["limits"], name
        assert "cpu" not in resources["limits"], name
        assert "cpu" in resources["requests"], name


def test_tmp_is_an_emptydir_because_the_root_is_read_only() -> None:
    for name, spec in pods().items():
        volume = next(v for v in spec["volumes"] if v["name"] == "tmp")
        assert volume["emptyDir"]["sizeLimit"] == "64Mi", name
        mounts = {m["mountPath"] for m in spec["containers"][0]["volumeMounts"]}
        assert "/tmp" in mounts, name


def test_the_api_rolls_without_losing_capacity() -> None:
    api = by_kind(render(), "Deployment")["shiptrack-api"]
    strategy = api["spec"]["strategy"]["rollingUpdate"]
    assert strategy == {"maxSurge": "25%", "maxUnavailable": 0}
    spec = pod_spec(api)
    assert spec["terminationGracePeriodSeconds"] == 45
    container = spec["containers"][0]
    assert container["lifecycle"]["preStop"] == {"sleep": {"seconds": 15}}
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["startupProbe"]["httpGet"]["path"] == "/healthz"


def test_the_api_replica_count_belongs_to_the_hpa() -> None:
    docs = render()
    assert "replicas" not in by_kind(docs, "Deployment")["shiptrack-api"]["spec"]
    hpa = by_kind(docs, "HorizontalPodAutoscaler")["shiptrack-api"]["spec"]
    assert (hpa["minReplicas"], hpa["maxReplicas"]) == (2, 10)
    assert hpa["metrics"][0]["resource"]["target"]["averageUtilization"] == 60
    assert hpa["behavior"]["scaleDown"]["stabilizationWindowSeconds"] == 300


def test_disruption_budgets() -> None:
    pdbs = by_kind(render(), "PodDisruptionBudget")
    assert pdbs["shiptrack-api"]["spec"]["minAvailable"] == 1
    assert pdbs["shiptrack-worker-events"]["spec"]["maxUnavailable"] == 1


def test_the_target_group_binding_points_at_the_service() -> None:
    binding = by_kind(render(), "TargetGroupBinding")["shiptrack-api"]["spec"]
    assert binding["serviceRef"] == {"name": "shiptrack-api", "port": 8000}
    assert binding["targetType"] == "ip"
    assert binding["networking"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8000}]
    service = by_kind(render(), "Service")["shiptrack-api"]["spec"]
    assert service["type"] == "ClusterIP"
    assert [p["port"] for p in service["ports"]] == [8000]


def test_keda_scales_the_workers_from_the_queues() -> None:
    docs = render()
    events = by_kind(docs, "ScaledObject")["shiptrack-worker-events"]["spec"]
    notify = by_kind(docs, "ScaledObject")["shiptrack-worker-notify"]["spec"]
    assert (events["minReplicaCount"], events["maxReplicaCount"]) == (1, 10)
    assert (notify["minReplicaCount"], notify["maxReplicaCount"]) == (0, 3)
    for scaled in (events, notify):
        trigger = scaled["triggers"][0]
        assert trigger["type"] == "aws-sqs-queue"
        assert trigger["metadata"]["queueLength"] == "20"
        assert trigger["authenticationRef"] == {"name": "shiptrack-aws"}
    auth = by_kind(docs, "TriggerAuthentication")["shiptrack-aws"]["spec"]
    assert auth == {"podIdentity": {"provider": "aws"}}
    assert "replicas" not in by_kind(docs, "Deployment")["shiptrack-worker-events"]["spec"]


def test_the_sla_scan_is_suspended_in_the_chart_and_live_in_dev() -> None:
    # The chart ships suspended; the dev environment turns it on in wave 3, after legacy's cron.
    assert yaml.safe_load((CHART / "values.yaml").read_text())["slaScan"]["suspend"] is True
    cron = by_kind(render(), "CronJob")["shiptrack-sla-scan"]["spec"]
    assert cron["suspend"] is False
    assert cron["schedule"] == "*/5 * * * *"
    assert cron["concurrencyPolicy"] == "Forbid"
    assert cron["startingDeadlineSeconds"] == 120
    job = cron["jobTemplate"]["spec"]
    assert (job["backoffLimit"], job["activeDeadlineSeconds"]) == (1, 240)
    held = by_kind(render("--set", "slaScan.suspend=true"), "CronJob")["shiptrack-sla-scan"]
    assert held["spec"]["suspend"] is True


def test_the_migration_job_is_a_hook_off_in_the_chart_and_on_in_dev() -> None:
    # The chart ships with it off; the dev environment turns it on at the schema handoff (§9.1).
    defaults = yaml.safe_load((CHART / "values.yaml").read_text())
    assert defaults["migrations"]["enabled"] is False
    assert "shiptrack-migrate" in by_kind(render(), "Job")
    assert "shiptrack-migrate" not in by_kind(render("--set", "migrations.enabled=false"), "Job")
    docs = render("--set", "migrations.enabled=true")
    job = by_kind(docs, "Job")["shiptrack-migrate"]
    annotations = job["metadata"]["annotations"]
    assert annotations["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert annotations["helm.sh/hook-weight"] == "-5"
    assert annotations["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"
    env = {e["name"]: e["value"] for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["SHIPTRACK_MIGRATIONS_ENABLED"] == "true"
    assert "SHIPTRACK_DB_MIGRATOR_SECRET_ARN" in env
    account = by_kind(docs, "ServiceAccount")["shiptrack-migrate"]
    assert account["metadata"]["annotations"]["helm.sh/hook-weight"] == "-10"


def test_service_accounts_match_the_pod_identity_associations() -> None:
    docs = render("--set", "migrations.enabled=true")
    names = set(by_kind(docs, "ServiceAccount"))
    assert names == {
        "shiptrack-api",
        "shiptrack-worker-events",
        "shiptrack-worker-notify",
        "shiptrack-sla-scan",
        "shiptrack-migrate",
    }
    for name, account in by_kind(docs, "ServiceAccount").items():
        assert account["automountServiceAccountToken"] is False, name
        assert "eks.amazonaws.com/role-arn" not in account["metadata"].get("annotations", {}), name


def test_the_network_is_denied_by_default() -> None:
    policies = by_kind(render(), "NetworkPolicy")
    deny = policies["shiptrack-default-deny-ingress"]["spec"]
    assert (
        deny["podSelector"] == {} and deny["policyTypes"] == ["Ingress"] and "ingress" not in deny
    )
    api = policies["shiptrack-allow-api-from-vpc"]["spec"]["ingress"][0]
    assert api["from"] == [{"ipBlock": {"cidr": "10.0.0.0/16"}}]
    assert api["ports"] == [{"protocol": "TCP", "port": 8000}]
    metrics = policies["shiptrack-allow-metrics-from-vpc"]["spec"]["ingress"][0]
    assert metrics["ports"] == [{"protocol": "TCP", "port": 9090}]


def test_pods_are_annotated_for_the_managed_scraper() -> None:
    for name, spec in {k: v for k, v in pods().items() if k.startswith("shiptrack-worker")}.items():
        assert spec["containers"][0]["ports"][0]["containerPort"] == 9090, name
    for deployment in by_kind(render(), "Deployment").values():
        annotations = deployment["spec"]["template"]["metadata"]["annotations"]
        assert annotations["prometheus.io/scrape"] == "true"
        assert annotations["prometheus.io/port"] == "9090"


def test_the_notify_worker_has_no_database_settings() -> None:
    env = {e["name"] for e in pods()["shiptrack-worker-notify"]["containers"][0]["env"]}
    assert not {n for n in env if "DB_" in n}
    assert "SHIPTRACK_NOTIFY_QUEUE_URL" in env


def test_each_role_sets_its_own_pool() -> None:
    def pool(name: str) -> tuple[str, str]:
        env = {e["name"]: e["value"] for e in pods()[name]["containers"][0]["env"]}
        return env["SHIPTRACK_DB_POOL_SIZE"], env["SHIPTRACK_DB_MAX_OVERFLOW"]

    assert pool("shiptrack-api") == ("4", "2")
    assert pool("shiptrack-worker-events") == ("2", "0")
    assert pool("shiptrack-sla-scan") == ("1", "1")


def test_no_account_id_or_secret_value_is_rendered() -> None:
    result = subprocess.run(
        ["helm", "template", "x", str(CHART), "-f", str(CHART / "ci-values.yaml")],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert "<ACCOUNT_ID>" in result.stdout  # placeholders only; real values come from SSM at deploy
    assert "AKIA" not in result.stdout


def test_a_digest_is_required() -> None:
    result = subprocess.run(
        ["helm", "template", "x", str(CHART), "-f", str(CHART / "ci-values.yaml"),
         "--set", "image.digest=latest"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode != 0
    assert "image/digest" in result.stderr


# The GCP render (GCP design 5.6). The AWS render above is untouched by these switches.


def gcp_env(name: str, docs: list[dict[str, Any]] | None = None) -> dict[str, str]:
    docs = docs or render_gcp()
    spec = pod_spec(
        by_kind(docs, "Deployment").get(name)
        or by_kind(docs, "CronJob").get(name)
        or by_kind(docs, "Job")[name]
    )
    return {e["name"]: e["value"] for e in spec["containers"][0]["env"]}


def test_the_aws_render_is_the_default_and_names_no_gcp_object() -> None:
    kinds = {d["kind"] for d in render()}
    assert "PodMonitoring" not in kinds
    assert {"TargetGroupBinding", "ScaledObject", "HorizontalPodAutoscaler"} <= kinds
    for spec in pods().values():
        assert "nodeSelector" not in spec
        names = {e["name"] for e in spec["containers"][0]["env"]}
        assert "SHIPTRACK_CLOUD" not in names
        assert not {n for n in names if "GCP" in n or "TOPIC" in n or "SUBSCRIPTION" in n}


def test_gcp_renders_no_aws_or_scaling_objects() -> None:
    kinds = {d["kind"] for d in render_gcp()}
    assert not kinds & {"TargetGroupBinding", "ScaledObject", "TriggerAuthentication"}
    assert "HorizontalPodAutoscaler" not in kinds
    assert "PodMonitoring" in kinds


def test_gcp_workers_run_at_fixed_replica_counts() -> None:
    deployments = by_kind(render_gcp(), "Deployment")
    assert deployments["shiptrack-api"]["spec"]["replicas"] == 2
    assert deployments["shiptrack-worker-events"]["spec"]["replicas"] == 1
    assert deployments["shiptrack-worker-notify"]["spec"]["replicas"] == 1
    bigger = by_kind(render_gcp("--set", "workerEvents.replicas=3"), "Deployment")
    assert bigger["shiptrack-worker-events"]["spec"]["replicas"] == 3


def test_gcp_pods_select_spot_capacity_when_asked() -> None:
    docs = render_gcp()
    specs = [
        pod_spec(d)
        for kind in ("Deployment", "CronJob", "Job")
        for d in by_kind(docs, kind).values()
    ]
    assert len(specs) == 5
    for spec in specs:
        assert spec["nodeSelector"] == {"cloud.google.com/gke-spot": "true"}
    off = render_gcp("--set", "spot=false")
    assert all("nodeSelector" not in pod_spec(d) for d in by_kind(off, "Deployment").values())


def test_gcp_settings_replace_the_aws_block() -> None:
    api = gcp_env("shiptrack-api")
    assert api["SHIPTRACK_CLOUD"] == "gcp"
    assert api["SHIPTRACK_GCP_PROJECT"] == "example-project"
    assert api["SHIPTRACK_DB_SECRET_NAME"] == "shiptrack-db-app"
    assert api["SHIPTRACK_EVENTS_TOPIC"] == "shiptrack-carrier-events"
    assert api["SHIPTRACK_PROOF_OF_DELIVERY_BUCKET"] == "example-project-proof-of-delivery"
    assert api["SHIPTRACK_PROOF_OF_DELIVERY_SIGNER"].endswith(".iam.gserviceaccount.com")

    events = gcp_env("shiptrack-worker-events")
    assert events["SHIPTRACK_EVENTS_SUBSCRIPTION"] == "shiptrack-carrier-events-worker"
    assert events["SHIPTRACK_NOTIFY_TOPIC"] == "shiptrack-notifications"

    notify = gcp_env("shiptrack-worker-notify")
    assert notify["SHIPTRACK_NOTIFY_SUBSCRIPTION"] == "shiptrack-notifications-worker"
    assert not {n for n in notify if "DB_" in n}

    assert gcp_env("shiptrack-sla-scan")["SHIPTRACK_DB_SECRET_NAME"] == "shiptrack-db-app"
    migrate = gcp_env("shiptrack-migrate")
    assert migrate["SHIPTRACK_DB_MIGRATOR_SECRET_NAME"] == "shiptrack-db-migrator"

    for name in ("shiptrack-api", "shiptrack-worker-events", "shiptrack-worker-notify"):
        names = set(gcp_env(name))
        assert not {n for n in names if "ARN" in n or "QUEUE_URL" in n or n == "AWS_REGION"}, name


def test_gcp_network_admits_only_the_managed_collectors() -> None:
    policies = by_kind(render_gcp(), "NetworkPolicy")
    assert set(policies) == {
        "shiptrack-default-deny-ingress",
        "shiptrack-allow-metrics-from-collectors",
    }
    rule = policies["shiptrack-allow-metrics-from-collectors"]["spec"]["ingress"][0]
    # Autopilot runs the managed collectors in gke-gmp-system; a self-deployed one uses gmp-system.
    assert rule["from"] == [
        {
            "namespaceSelector": {
                "matchExpressions": [
                    {
                        "key": "kubernetes.io/metadata.name",
                        "operator": "In",
                        "values": ["gmp-system", "gke-gmp-system"],
                    }
                ]
            }
        }
    ]
    assert rule["ports"] == [{"protocol": "TCP", "port": 9090}]


def test_gcp_metrics_are_scraped_from_the_ops_port_every_minute() -> None:
    monitoring = by_kind(render_gcp(), "PodMonitoring")["shiptrack"]["spec"]
    assert monitoring["endpoints"] == [{"port": "ops", "path": "/metrics", "interval": "60s"}]
    assert monitoring["selector"]["matchLabels"]["app.kubernetes.io/name"] == "shiptrack"


def test_gcp_service_accounts_carry_no_cloud_annotation() -> None:
    for name, account in by_kind(render_gcp(), "ServiceAccount").items():
        assert account["automountServiceAccountToken"] is False, name
        annotations = set(account["metadata"].get("annotations", {}))
        assert not {a for a in annotations if "iam.gke.io" in a or "eks.amazonaws.com" in a}, name


def helm_fails(values: str, *extra: str) -> str:
    result = subprocess.run(
        ["helm", "template", "x", str(CHART), "-f", str(CHART / values), *extra],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode != 0
    return result.stderr


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (["--set", "scaling.mode=keda"], "/scaling/mode"),
        (["--set", "gcp.project="], "/gcp/project"),
        (["--set", "gcp.proofOfDeliverySigner=someone"], "/gcp/proofOfDeliverySigner"),
        (["--set", "gcp.eventsTopic="], "/gcp/eventsTopic"),
        (["--set", "image.digest=latest"], "image/digest"),
    ],
)
def test_the_gcp_schema_rejects_what_the_gcp_run_cannot_use(args: list[str], needle: str) -> None:
    assert needle in helm_fails("ci-values-gcp.yaml", *args)


def test_spot_is_refused_on_aws_and_the_cloud_must_be_known() -> None:
    assert "/spot" in helm_fails("ci-values.yaml", "--set", "spot=true")
    assert "/cloud" in helm_fails("ci-values.yaml", "--set", "cloud=azure")


def test_a_gcp_render_needs_no_aws_values_and_names_no_real_project() -> None:
    result = subprocess.run(
        ["helm", "template", "x", str(CHART), "-f", str(CHART / "ci-values-gcp.yaml")],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert "example-project" in result.stdout  # placeholders only; real values arrive with --set
    assert "<ACCOUNT_ID>" not in result.stdout
