"""Read-only host metrics and scoped sleep inhibition during worker jobs."""
import contextlib
import ctypes
import os
import shutil
import struct
import time
from pathlib import Path


def _count_core_records(data: bytes) -> int | None:
    """Count physical-core records in a Windows processor-topology response."""
    offset = 0
    count = 0
    while offset + 8 <= len(data):
        relationship, size = struct.unpack_from("<II", data, offset)
        if size < 8 or offset + size > len(data):
            return None
        count += relationship == 0  # RelationProcessorCore
        offset += size
    return count if offset == len(data) and count else None


def physical_core_count() -> int | None:
    """Read all physical cores using the Windows processor topology API."""
    if os.name != "nt":
        return None
    from ctypes import wintypes

    query = ctypes.windll.kernel32.GetLogicalProcessorInformationEx
    query.argtypes = (wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
    query.restype = wintypes.BOOL
    length = wintypes.DWORD(0)
    query(0, None, ctypes.byref(length))
    if length.value < 8:
        return None
    buffer = ctypes.create_string_buffer(length.value)
    if not query(0, buffer, ctypes.byref(length)):
        return None
    return _count_core_records(buffer.raw[:length.value])


def hardware_identity() -> dict:
    """Read CPU topology, model and power without WMI or solver imports."""
    model, ac_power, battery_percent = None, None, None
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                model = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
        class PowerStatus(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ubyte) for name in ("ac", "flag", "percent", "reserved")] + [
                ("life", ctypes.c_ulong), ("full_life", ctypes.c_ulong)]
        status = PowerStatus()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            ac_power = bool(status.ac) if status.ac in (0, 1) else None
            battery_percent = status.percent if status.percent <= 100 else None
    return {"cpu_model": model, "cpu_physical_cores": physical_core_count(),
            "ac_power": ac_power, "battery_percent": battery_percent}


def installed_ram_gb() -> float | None:
    """Physical DIMM capacity, distinct from OS-usable and currently free RAM."""
    if os.name != "nt":
        return None
    size = ctypes.c_ulonglong()
    query = ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory
    query.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
    query.restype = ctypes.c_int
    return size.value / 1024**2 if query(ctypes.byref(size)) and size.value else None


def memory_metrics() -> dict:
    if os.name == "nt":
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
        status = Status()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"ram_gb": round(status.total / 1024**3, 2), "ram_free_gb": round(status.available / 1024**3, 2),
                    # MEMORYSTATUSEX page fields are commit capacity, not free disk
                    # or physical RAM. They may also reflect a process/job quota.
                    "commit_limit_gb": round(status.page_total / 1024**3, 2),
                    "commit_available_gb": round(status.page_available / 1024**3, 2),
                    "installed_ram_gb": installed_ram_gb()}
    elif Path("/proc/meminfo").is_file():
        values = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
        return {"ram_gb": round(values["MemTotal"] / 1024**2, 2), "ram_free_gb": round(values["MemAvailable"] / 1024**2, 2)}
    return {"ram_gb": None, "ram_free_gb": None}


def cpu_percent() -> float | None:
    if os.name != "nt":
        return None
    def sample():
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return idle.value, kernel.value + user.value
    first = sample()
    time.sleep(0.1)
    second = sample()
    if not first or not second or second[1] <= first[1]:
        return None
    return round(max(0, min(100, 100 * (1 - (second[0]-first[0]) / (second[1]-first[1])))), 1)


def disk_free_gb(workspace: Path) -> float:
    existing = workspace.resolve()
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    return round(shutil.disk_usage(existing).free / 1024**3, 2)


@contextlib.contextmanager
def keep_awake():
    """Prevent idle sleep while this thread runs; restore on exit, never change global power policy."""
    enabled = False
    if os.name == "nt":
        enabled = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
        if not enabled:
            raise OSError("Unable to prevent idle sleep during worker execution")
    try:
        yield enabled
    finally:
        if enabled:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
