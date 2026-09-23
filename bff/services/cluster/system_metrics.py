"""Read-only host metrics and scoped sleep inhibition during worker jobs."""
import contextlib
import ctypes
import os
import shutil
import time
from pathlib import Path


def hardware_identity() -> dict:
    """Read model and power source without WMI subprocesses or solver imports."""
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
    return {"cpu_model": model, "ac_power": ac_power, "battery_percent": battery_percent}


def memory_metrics() -> dict:
    if os.name == "nt":
        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
        status = Status()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"ram_gb": round(status.total / 1024**3, 2), "ram_free_gb": round(status.available / 1024**3, 2)}
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
