"""Per-PC Named-User licenses allow more than two concurrent Gurobi slots."""
import pytest

from bff.services.cluster.contracts import ClusterConfig
from bff.services.cluster.license_broker import LicenseBroker
from bff.services.cluster.store import JobStore


def test_config_accepts_more_than_two_slots_but_not_unbounded():
    assert ClusterConfig(global_gurobi_slots=6).global_gurobi_slots == 6
    with pytest.raises(ValueError):
        ClusterConfig(global_gurobi_slots=65)


def test_broker_admits_exactly_the_configured_six_slots(tmp_path):
    broker = LicenseBroker(JobStore(tmp_path), total=6, external=0)
    assert sum(broker.acquire(str(i), owner_kind="remote") for i in range(10)) == 6
    with pytest.raises(ValueError):
        LicenseBroker(JobStore(tmp_path), total=65, external=0)
