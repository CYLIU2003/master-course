"""Physical core count is distinct from logical CPU threads."""
import os
import struct

from bff.services.cluster.system_metrics import _count_core_records, physical_core_count
from bff.services.cluster.system_metrics import installed_ram_gb, memory_metrics


def test_counts_only_complete_processor_core_records():
    records = b"".join(struct.pack("<II", relationship, 8) for relationship in (0, 1, 0))
    assert _count_core_records(records) == 2
    assert _count_core_records(records[:-1]) is None
    assert _count_core_records(struct.pack("<II", 0, 0)) is None


def test_windows_physical_cores_are_bounded_by_logical_threads():
    if os.name != "nt":
        return
    cores = physical_core_count()
    assert cores is not None
    assert 0 < cores <= (os.cpu_count() or 0)


def test_windows_installed_ram_is_distinct_from_os_usable_ram():
    if os.name != "nt":
        return
    installed = installed_ram_gb()
    usable = memory_metrics()["ram_gb"]
    assert installed is not None and installed >= usable


def test_windows_commit_capacity_is_reported_separately():
    if os.name != 'nt':
        return
    metrics = memory_metrics()
    assert 0 <= metrics['commit_available_gb'] <= metrics['commit_limit_gb']
    assert metrics['commit_limit_gb'] >= metrics['ram_gb']
