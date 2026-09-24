import errno
import os
from pathlib import Path
import threading
import time

import pytest

from tools.cluster import atomic_file


def test_transient_access_denied_preserves_then_replaces_original(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_bytes(b"old")
    original = Path.replace
    attempts = []
    def sharing_lock(path, destination):
        attempts.append(path)
        if len(attempts) < 3:
            assert target.read_bytes() == b"old"
            raise PermissionError("reader sharing lock")
        return original(path, destination)
    monkeypatch.setattr(Path, "replace", sharing_lock)
    monkeypatch.setattr(atomic_file.time, "sleep", lambda value: None)
    atomic_file.replace_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert len(attempts) == 3 and len(set(attempts)) == 1


def test_persistent_access_denied_keeps_original_and_new_evidence(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_bytes(b"old")
    monkeypatch.setattr(Path, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("denied")))
    monkeypatch.setattr(atomic_file.time, "sleep", lambda value: None)
    with pytest.raises(PermissionError):
        atomic_file.replace_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert [p.read_bytes() for p in tmp_path.glob("*.tmp")] == [b"new"]


def test_disk_full_does_not_delete_previous_state(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_bytes(b"old")
    monkeypatch.setattr(Path, "write_bytes", lambda *a: (_ for _ in ()).throw(OSError(errno.ENOSPC, "disk full")))
    with pytest.raises(OSError) as exc:
        atomic_file.replace_bytes(target, b"new")
    assert exc.value.errno == errno.ENOSPC
    assert target.read_bytes() == b"old"


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing-mode integration test")
def test_real_windows_reader_blocks_replace_then_recovery_succeeds(tmp_path):
    import ctypes
    from ctypes import wintypes
    target = tmp_path / "state.json"
    target.write_bytes(b"old")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Read sharing allowed, delete sharing deliberately absent: the observed failure.
    handle = kernel.CreateFileW(str(target), 0x80000000, 1, None, 3, 0, None)
    assert handle != wintypes.HANDLE(-1).value
    def release():
        time.sleep(.15)
        kernel.CloseHandle(handle)
    thread = threading.Thread(target=release)
    thread.start()
    try:
        atomic_file.replace_bytes(target, b"new")
    finally:
        thread.join()
    assert target.read_bytes() == b"new"
