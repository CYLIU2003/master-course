"""Physical core count is distinct from logical CPU threads."""
import os
import struct

from bff.services.cluster.system_metrics import _count_core_records, physical_core_count


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
