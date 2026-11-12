"""Native process birth identity. No name matching, rounded dates or PID-only signals."""

import json
import os
from pathlib import Path


def windows_kernel():
    import ctypes
    from ctypes import wintypes as w

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    k.GetProcessTimes.restype = w.BOOL
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k.WaitForSingleObject.restype = w.DWORD
    return k


def windows_birth(handle, pid):
    import ctypes
    from ctypes import wintypes as w

    times = [w.FILETIME() for _ in range(4)]
    if not windows_kernel().GetProcessTimes(handle, *(ctypes.byref(x) for x in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return {"version": 1, "pid": pid, "clock": "WINDOWS_FILETIME_100NS", "created": str(ticks)}


def _probe(pid, handle=None):
    """None means the PID is absent. Errors must remain UNKNOWN to the caller."""
    if os.name == "nt":
        import ctypes

        k = windows_kernel()
        owned = handle is None
        if owned:
            handle = k.OpenProcess(0x1000 | 0x100000, False, pid)
            if not handle:
                error = ctypes.get_last_error()
                if error == 87:  # ERROR_INVALID_PARAMETER: no such process.
                    return None
                raise ctypes.WinError(error)
        try:
            identity = windows_birth(handle, pid)
            wait = k.WaitForSingleObject(handle, 0)
            if wait not in (0, 258):
                raise OSError("Cannot establish process exit state")
            return identity, wait == 258
        finally:
            if owned:
                k.CloseHandle(handle)
    # Linux identity includes boot ID: start ticks alone repeat across reboots.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        if Path("/proc/self/stat").exists():
            return None
        raise OSError("Native process birth identity unsupported on this OS") from None
    fields = stat[stat.rfind(")") + 2 :].split()
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return {
        "version": 1,
        "pid": pid,
        "clock": "LINUX_BOOT_START_TICKS",
        "created": fields[19],
        "boot_id": boot,
    }, fields[0] not in {"Z", "X"}


def capture(pid, handle=None):
    result = _probe(pid, handle)
    if result is None:
        raise ProcessLookupError("Process disappeared before its birth identity was captured")
    if not _valid(result[0], pid):
        raise ValueError("Native process birth identity is incomplete")
    return result[0]


def _valid(identity, pid):
    return (
        isinstance(identity, dict)
        and type(identity.get("version")) is int
        and identity.get("version") == 1
        and type(identity.get("pid")) is int
        and identity.get("pid") == pid
        and 0 < pid <= 0xFFFFFFFF
        and isinstance(identity.get("created"), str)
        and identity["created"].isdigit()
        and 0 < int(identity["created"]) < 2**64
        and str(int(identity["created"])) == identity["created"]
        and (
            (
                identity.get("clock") == "WINDOWS_FILETIME_100NS"
                and set(identity) == {"version", "pid", "clock", "created"}
            )
            or (
                identity.get("clock") == "LINUX_BOOT_START_TICKS"
                and isinstance(identity.get("boot_id"), str)
                and bool(identity["boot_id"])
                and set(identity) == {"version", "pid", "clock", "created", "boot_id"}
            )
        )
    )


def identity_state(pid, identity=None):
    if pid is None:
        return "NOT_RECORDED" if identity is None else "UNKNOWN"
    if not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid <= 0xFFFFFFFF:
        return "UNKNOWN"
    try:
        if isinstance(identity, str):
            identity = json.loads(identity)
        current = _probe(pid)
        if current is None:
            return "EXITED"
        if not _valid(identity, pid):
            return "UNKNOWN"  # Legacy/incomplete identity: never invent a birth time.
        observed, running = current
        if not _valid(observed, pid) or observed["clock"] != identity["clock"]:
            return "UNKNOWN"
        if observed != identity:
            return "REUSED"
        return "RUNNING" if running else "EXITED"
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return "UNKNOWN"


def pending(row):
    """False only establishes stopped/not launched; it never certifies success."""
    row = dict(row)
    if row.get("child_pid") is None and row.get("status") in {"RUNNING", "UNKNOWN"}:
        return True
    return identity_state(row.get("child_pid"), row.get("process_identity_json")) in {
        "RUNNING",
        "UNKNOWN",
    }


def inspected(row):
    row = dict(row)
    row["process_state"] = identity_state(row.get("child_pid"), row.get("process_identity_json"))
    return row


def record_process(conn, table, key, identifier, identity):
    # Explicit internal table allowlist, never an identifier from a model/request.
    if (table, key) not in {
        ("attempts", "attempt_id"),
        ("executions", "execution_id"),
        ("manual_repairs", "repair_id"),
    }:
        raise ValueError("Invalid supervised process owner")
    pid = identity["pid"] if isinstance(identity, dict) else identity
    if isinstance(identity, dict) and not _valid(identity, pid):
        raise ValueError("Cannot persist an incomplete new process identity")
    encoded = json.dumps(identity, sort_keys=True) if isinstance(identity, dict) else None
    conn.execute(
        f"UPDATE {table} SET child_pid=?,process_identity_json=? WHERE {key}=?",
        (pid, encoded, identifier),
    )


def migrate_v7(conn):
    for table in ("attempts", "executions", "manual_repairs"):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN process_identity_json TEXT")
    conn.execute("PRAGMA user_version=7")
