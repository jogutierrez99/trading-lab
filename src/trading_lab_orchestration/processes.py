"""Bounded argv-only processes and an OS-owned coordinator lock; never read credentials."""

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .process_identity import capture


def safe_environment(workspace: Path, *, omit: tuple[str, ...] = ()) -> dict[str, str]:
    # Drop inherited secret variables by NAME only. Authentication stays with Codex CLI.
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() != "OPENAI_ADMIN_KEY"
        and key.upper() not in omit
        and not any(
            word in key.upper()
            for word in (
                "TOKEN",
                "SECRET",
                "PASSWORD",
                "PASSPHRASE",
                "API_KEY",
                "COOKIE",
                "CREDENTIAL",
                "PRIVATE_KEY",
                "OKX_",
            )
        )
    }
    env["PYTHONPATH"] = str(workspace / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@contextmanager
def coordinator_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another implementation coordinator owns the OS lock") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class WindowsJob:
    """Kill-on-close job. Child starts suspended and is assigned before it can spawn."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [
                ("ProcessTime", ctypes.c_int64),
                ("JobTime", ctypes.c_int64),
                ("LimitFlags", w.DWORD),
                ("MinWorkingSet", ctypes.c_size_t),
                ("MaxWorkingSet", ctypes.c_size_t),
                ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", w.DWORD),
                ("SchedulingClass", w.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOps",
                    "WriteOps",
                    "OtherOps",
                    "ReadBytes",
                    "WriteBytes",
                    "OtherBytes",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("Basic", Basic),
                ("IO", IO),
                ("ProcessMemory", ctypes.c_size_t),
                ("JobMemory", ctypes.c_size_t),
                ("PeakProcessMemory", ctypes.c_size_t),
                ("PeakJobMemory", ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [w.LPVOID, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process: subprocess.Popen) -> None:
        import ctypes

        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    @staticmethod
    def resume(process: subprocess.Popen) -> None:
        import ctypes
        from ctypes import wintypes as w

        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtResumeProcess.argtypes = [w.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        if ntdll.NtResumeProcess(int(process._handle)) != 0:
            raise OSError("Unable to resume supervised child")

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run_process(
    argv: list[str],
    cwd: Path,
    timeout: float,
    stdout: Path,
    stderr: Path,
    input_text: str | None = None,
    on_start: Callable[[dict], None] | None = None,
    *,
    omit_env: tuple[str, ...] = (),
) -> dict:
    """Exclusive logs, external wall limit and full process-tree termination."""
    started = time.monotonic()
    if os.name != "nt" and not (hasattr(os, "pidfd_open") and Path("/proc/self/stat").exists()):
        raise ValueError("Safe supervision requires Windows handles or Linux pidfd/procfs")
    job = WindowsJob() if os.name == "nt" else None
    process = None
    timed_out = False
    identity = None
    pidfd = None
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=safe_environment(cwd, omit=omit_env),
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                shell=False,
                creationflags=(0x00000004 | 0x08000000) if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if job:
                job.assign(process)
            elif hasattr(os, "pidfd_open"):
                pidfd = os.pidfd_open(process.pid)
            identity = capture(process.pid, int(process._handle) if os.name == "nt" else None)
            if on_start:
                on_start(identity)
            if job:
                job.resume(process)
            try:
                if job:
                    process.communicate(
                        input=input_text.encode("utf-8") if input_text is not None else None,
                        timeout=max(0.001, timeout),
                    )
                else:
                    import select

                    # Do not reap the group leader until group cleanup: its retained
                    # PID prevents a foreign process group from acquiring the same ID.
                    def feed():
                        try:
                            if input_text is not None:
                                process.stdin.write(input_text.encode("utf-8"))
                            process.stdin.close()
                        except (BrokenPipeError, OSError):
                            pass

                    threading.Thread(target=feed, daemon=True).start()
                    if not select.select([pidfd], [], [], max(0.001, timeout))[0]:
                        raise subprocess.TimeoutExpired(argv, timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        if job:
            job.close()  # Also kills descendants when the leader has already exited.
        elif process and process.returncode is None:
            # This Popen child has not been reaped: its PID/group cannot be
            # reassigned while we check birth and signal, with no intervening wait.
            try:
                if identity is not None and capture(process.pid) == identity:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process:
            if process.returncode is None:
                if os.name == "nt":
                    # Popen owns the original kernel handle, never a reopened PID.
                    # Also covers assignment/capture failure while still suspended.
                    process.kill()
                elif pidfd is not None:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                else:
                    raise ValueError(
                        "Cannot safely terminate child without a pinned process handle"
                    )
            process.wait(timeout=10)
            if os.name == "nt":
                from .process_identity import windows_kernel

                if windows_kernel().WaitForSingleObject(int(process._handle), 10000) != 0:
                    raise ValueError("Original process termination is not confirmed")
        if pidfd is not None:
            os.close(pidfd)
    return {
        "argv": argv,
        "pid": process.pid,
        "process_identity": identity,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "duration_seconds": time.monotonic() - started,
        "stdout": str(stdout),
        "stderr": str(stderr),
    }
