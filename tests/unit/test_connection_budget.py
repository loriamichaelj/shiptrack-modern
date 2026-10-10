"""ADR-0002: the worst-case database connections stay within 60% of max_connections."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts" / "shiptrack"

# db.t4g.medium and db.t3.medium both allow about 400 connections (LEAST(memory / 9531392, 5000)).
# The deployed value is /shiptrack/platform/db_max_connections; this is the design's figure.
DB_MAX_CONNECTIONS = 400
BUDGET = int(DB_MAX_CONNECTIONS * 0.6)

# Legacy keeps running during coexistence (ADR-0002): 2 hosts x 4 workers x SQLAlchemy's default
# pool of 15, the SLA cron on both hosts, and PodSync plus the evidence scripts.
LEGACY_APP = 2 * 4 * 15
LEGACY_SLA_CRON = 2 * 2
LEGACY_PODSYNC_AND_EVIDENCE = 2 * 2 + 2


def values() -> dict:
    base = yaml.safe_load((CHART / "values.yaml").read_text())
    dev = yaml.safe_load((CHART / "values-dev.yaml").read_text())
    return merge(base, dev)


def merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def connections(pool: dict) -> int:
    return int(pool["size"]) + int(pool["maxOverflow"])


def worst_case(v: dict) -> int:
    api = v["api"]["hpa"]["maxReplicas"] * connections(v["api"]["pool"])
    events = v["workerEvents"]["keda"]["maxReplicaCount"] * connections(v["workerEvents"]["pool"])
    one_shots = connections(v["slaScan"]["pool"]) + connections(v["migrations"]["pool"])
    legacy = LEGACY_APP + LEGACY_SLA_CRON + LEGACY_PODSYNC_AND_EVIDENCE
    return legacy + api + events + one_shots


def test_the_dev_values_stay_within_the_budget() -> None:
    total = worst_case(values())
    assert total <= BUDGET, f"{total} connections in the worst case; the budget is {BUDGET}"


def test_the_arithmetic_matches_the_adr() -> None:
    assert worst_case(values()) == 214


def test_raising_the_api_ceiling_is_caught() -> None:
    v = values()
    v["api"]["hpa"]["maxReplicas"] = 40
    assert worst_case(v) > BUDGET


def test_the_notify_worker_has_no_database_pool() -> None:
    assert "pool" not in values()["workerNotify"]
