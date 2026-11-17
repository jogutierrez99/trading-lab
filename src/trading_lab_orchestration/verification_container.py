"""Fail-closed Linux containment for the authorized GitHub pilot verifier."""

import base64
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from .contracts import canonical, digest
from .processes import run_process
from .workspaces import file_hash, write_json

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(__file__).parent
ENDPOINT = "npipe:////./pipe/dockerDesktopLinuxEngine"
IMAGE_VARIABLE = "TRADING_LAB_VERIFICATION_IMAGE"
FLAGS = (
    "--pull=never",
    "--network=none",
    "--ipc=none",
    "--cgroupns=private",
    "--read-only",
    "--user=65534:65534",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--pids-limit=64",
    "--memory=768m",
    "--memory-swap=768m",
    "--cpus=1",
    "--ulimit=nofile=256:256",
    "--ulimit=core=0:0",
    "--no-healthcheck",
    "--log-driver=none",
    "--tmpfs=/work:rw,noexec,nosuid,nodev,size=32m,mode=1777",
    "--entrypoint=/usr/local/bin/python",
)
RUNTIME_FILES = (
    "__init__.py",
    "contracts.py",
    "implementation_contracts.py",
    "circuit_contracts.py",
    "native_interface.py",
)
NATIVE = """
import json
from pathlib import Path
from trading_lab_orchestration.implementation_contracts import ImplementationRequest
from trading_lab_orchestration.native_interface import implementation_interface
request = ImplementationRequest.model_validate_json(Path('request.json').read_bytes())
print(json.dumps(implementation_interface(request)))
"""

PROBE = """
import errno, os, socket, subprocess, sys
from pathlib import Path

def blocked(name, operation, allowed_errors):
    try:
        operation()
    except OSError as exc:
        if exc.errno not in allowed_errors:
            raise
        print(name + ': blocked', flush=True)
    else:
        raise RuntimeError(name + ': unexpectedly permitted')

def checks():
    assert os.geteuid() == 65534
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
    assert status['NoNewPrivs'].strip() == '1'
    assert status['Seccomp'].strip() == '2'
    assert int(status['CapEff'].strip(), 16) == 0
    cgroups = Path('/sys/fs/cgroup')
    assert (cgroups / 'memory.max').read_text().strip() == str(768 * 1024**2)
    assert (cgroups / 'memory.swap.max').read_text().strip() == '0'
    assert (cgroups / 'pids.max').read_text().strip() == '64'
    quota, period = (cgroups / 'cpu.max').read_text().split()
    assert int(quota) == int(period)
    assert {name for _, name in socket.if_nameindex()} == {'lo'}
    denied = (errno.EACCES, errno.EROFS, errno.ENOENT, errno.EPERM)
    blocked('external write', lambda: Path('/outside-canary').write_text('x'), denied)
    blocked('relative escape', lambda: Path('../outside-canary').write_text('x'), denied)
    blocked('external temp', lambda: Path('/tmp/outside-canary').write_text('x'), denied)
    for path in sys.argv[1:]:
        blocked('host fixture read', lambda: Path(path).read_bytes(), denied)
        blocked('host fixture write', lambda: Path(path).write_text('x'), denied)
    for path in ('/var/run/docker.sock', '/run/docker.sock'):
        assert not Path(path).exists()
    Path('escape').unlink(missing_ok=True)
    Path('escape').symlink_to('/tmp/outside-canary')
    blocked('symlink write', lambda: Path('escape').write_text('x'), denied)
    blocked('external TCP', lambda: socket.create_connection(('192.0.2.1', 443), 1),
            (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM))
    blocked('VM-to-host socket', lambda: socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM),
            (errno.EACCES, errno.EPERM, errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT))
    blocked('external DNS', lambda: socket.getaddrinfo('trading-lab-probe.invalid', 443),
            (socket.EAI_AGAIN, socket.EAI_NONAME, socket.EAI_FAIL))
    assert not any('API_KEY' in key or 'TOKEN' in key for key in os.environ)
    Path('inside-canary').write_text('ok')
    assert Path('inside-canary').read_text() == 'ok'

checks()
if not os.environ.get('TRADING_LAB_PROBE_CHILD'):
    subprocess.run([sys.executable, '-I', '-B', __file__, *sys.argv[1:]], check=True,
                   env=os.environ | {'TRADING_LAB_PROBE_CHILD': '1'}, timeout=10)
    import pandas, numpy, pyarrow, pydantic, yaml, pytest, ruff
    print('ISOLATION_PROBE_OK')
"""


class IsolationUnavailable(ValueError):
    """The required environment or its invariant checks failed."""


class IsolationUncertain(RuntimeError):
    """A daemon-side job might still exist; never retry the launch."""


def _docker_executable():
    if os.name == "nt":
        candidates = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker/Docker"]
        if local := os.environ.get("LOCALAPPDATA"):
            candidates.insert(0, Path(local) / "Programs/DockerDesktop")
        for root in candidates:
            executable = root / "resources/bin/docker.exe"
            if executable.is_absolute() and executable.is_file():
                return executable
    raise IsolationUnavailable("Docker Desktop Linux verifier is unavailable on Windows")


def _regular_bytes(root, relative):
    path = root
    parts = Path(relative).parts
    if Path(relative).is_absolute() or any(part == ".." or ":" in part for part in parts):
        raise IsolationUnavailable("Nonlocal verification archive entry")
    for part in ("", *parts):
        path /= part
        metadata = path.lstat()
        if path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise IsolationUnavailable("Linked or reparse-point verification input")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size > 1024 * 1024
    ):
        raise IsolationUnavailable("Verification input must be a small regular file")
    return path.read_bytes()


def _payload(files):
    if sum(map(len, files.values())) > 12 * 1024 * 1024:
        raise IsolationUnavailable("Verification archive exceeds its limit")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _base_sources(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise IsolationUnavailable("Verification requires an exact frozen commit")
    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "archive",
            "--format=tar",
            commit,
            "--",
            "src/quant_lab",
            "configs/app.yaml",
            "configs/risk.yaml",
            "pyproject.toml",
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode or len(result.stdout) > 12 * 1024 * 1024:
        raise IsolationUnavailable("Could not obtain frozen verifier sources")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        for member in archive:
            if member.isdir():
                continue
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                raise IsolationUnavailable("Unexpected frozen verifier entry")
            files[member.name] = archive.extractfile(member).read()
    return files


class VerificationContainer:
    def __init__(self):
        self.image = os.environ.get(IMAGE_VARIABLE, "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise IsolationUnavailable(f"Set {IMAGE_VARIABLE} to the reviewed local image ID")
        self.docker = _docker_executable()
        self.guest = (RUNTIME / "verification_guest.py").read_text(encoding="utf-8")
        self.fingerprint = digest(
            canonical(
                {
                    "image": self.image,
                    "endpoint": ENDPOINT,
                    "flags": FLAGS,
                    "docker_sha256": file_hash(self.docker),
                    "supervisor_sha256": file_hash(Path(__file__)),
                    "process_supervisor_sha256": file_hash(RUNTIME / "processes.py"),
                    "coordinator_sha256": file_hash(RUNTIME / "implementation.py"),
                    "launch_controls_sha256": file_hash(RUNTIME / "pilot_launch.py"),
                    "guest_sha256": digest(self.guest),
                    "probe_sha256": digest(PROBE),
                    "native_sources": {name: file_hash(RUNTIME / name) for name in RUNTIME_FILES},
                }
            )
        )

    def _cli(self, arguments, folder, name, timeout, payload=None):
        config = folder / "docker-config"
        config.mkdir(exist_ok=True)
        return run_process(
            [str(self.docker), "--config", str(config), "--host", ENDPOINT, *arguments],
            folder,
            timeout,
            folder / f"{name}.stdout",
            folder / f"{name}.stderr",
            payload,
            omit_env=tuple(key.upper() for key in os.environ if key.upper().startswith("DOCKER_")),
            output_limit=768 * 1024,
        )

    @staticmethod
    def _ok(result):
        return not (result["timed_out"] or result["exit_code"] or result["output_truncated"])

    def _execute(self, command, payload, folder, name, timeout):
        container = "tl-pilot-verify-" + uuid4().hex
        write_json(
            folder / f"{name}-container.json",
            {
                "container": container,
                "verification_sha256": self.fingerprint,
                "payload_sha256": digest(payload),
            },
        )
        try:
            result = self._cli(
                [
                    "run",
                    "--interactive",
                    "--name",
                    container,
                    *FLAGS,
                    self.image,
                    "-I",
                    "-B",
                    "-c",
                    self.guest,
                    str(min(timeout, 120)),
                    *command,
                ],
                folder,
                name,
                timeout,
                payload,
            )
        finally:
            try:
                cleanup = self._cli(["rm", "--force", container], folder, f"{name}-cleanup", 8)
                write_json(folder / f"{name}-cleanup.json", cleanup)
                if not self._ok(cleanup):
                    raise IsolationUncertain(f"Container cleanup not confirmed: {container}")
            except (OSError, ValueError) as exc:
                raise IsolationUncertain(f"Container cleanup not confirmed: {container}") from exc
        return result

    def preflight(self):
        with tempfile.TemporaryDirectory(prefix="tl-verification-preflight-") as temporary:
            root = Path(temporary)
            info = self._cli(["image", "inspect", self.image], root, "image", 8)
            if not self._ok(info):
                raise IsolationUnavailable("Local Linux engine or reviewed image is unavailable")
            images = json.loads(Path(info["stdout"]).read_bytes())
            if not isinstance(images, list) or len(images) != 1:
                raise IsolationUnavailable("Unexpected Docker image metadata")
            image = images[0]
            if (
                image["Os"] != "linux"
                or image["Id"] != self.image
                or image["Config"].get("Volumes")
            ):
                raise IsolationUnavailable("Verifier image must be Linux, pinned and volume-free")
            canary = root / "host-canary.txt"
            canary.write_text("trading-lab-isolation-fixture", encoding="utf-8")
            before = file_hash(canary)
            drive = canary.drive[:1].lower()
            tail = canary.as_posix()[3:]
            command = [
                "probe.py",
                f"/run/desktop/mnt/host/{drive}/{tail}",
                f"/host_mnt/{drive}/{tail}",
                f"/mnt/{drive}/{tail}",
            ]
            result = self._execute(
                command, _payload({"probe.py": PROBE.encode()}), root, "probe", 30
            )
            output = Path(result["stdout"]).read_text(encoding="utf-8", errors="replace")
            if not self._ok(result) or output.splitlines()[-1:] != ["ISOLATION_PROBE_OK"]:
                raise IsolationUnavailable("Container isolation or dependency probe failed")
            if file_hash(canary) != before:
                raise IsolationUnavailable("Host isolation test fixture changed")
            return {
                "verification_sha256": self.fingerprint,
                "image": self.image,
                "host_canary_sha256": before,
                "probe": output.splitlines(),
            }

    def confirm_cleanup(self, container):
        if not re.fullmatch(r"tl-pilot-verify-[0-9a-f]{32}", container):
            raise IsolationUnavailable("Invalid persisted verification container identity")
        with tempfile.TemporaryDirectory(prefix="tl-verification-reconcile-") as temporary:
            result = self._cli(
                ["container", "ls", "--all", "--quiet", "--filter", f"name=^/{container}$"],
                Path(temporary),
                "reconcile",
                8,
            )
            if not self._ok(result) or Path(result["stdout"]).read_bytes().strip():
                raise IsolationUnavailable(f"Container absence not confirmed: {container}")

    def verify(self, request, files, actual, evidence, deadline):
        sources = _base_sources(request.base_commit)
        for name in RUNTIME_FILES:
            sources[f"src/trading_lab_orchestration/{name}"] = _regular_bytes(RUNTIME, name)
        for name in request.allowed_write_paths:
            delivered = _regular_bytes(files, name)
            if hashlib.sha256(delivered).hexdigest() != actual[name]:
                raise IsolationUnavailable("Verification snapshot contradicts the sealed delivery")
            sources[name] = delivered
        sources["request.json"] = canonical(
            request.model_copy(update={"workspace": "/work"}).model_dump(mode="json")
        ).encode("utf-8")
        payload = _payload(sources)
        checks = []
        commands = [command[1:] for command in request.authorized_checks] + [["-c", NATIVE]]
        for index, command in enumerate(commands):
            name = f"check-{index}"
            timeout = min(request.plan.check_timeout_seconds, deadline - time.monotonic())
            if timeout <= 0:
                raise IsolationUnavailable("Implementation wall limit exhausted before checks")
            result = self._execute(command, payload, evidence, name, timeout)
            if index < len(request.authorized_checks):
                result["authorized_argv"] = request.authorized_checks[index]
                checks.append(result)
            write_json(evidence / f"{name}.json", result)
            if not self._ok(result):
                raise ValueError(f"Isolated implementation check failed: {name}")
        try:
            report = json.loads(Path(result["stdout"]).read_bytes().splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise ValueError("Native interface verification did not produce a report") from exc
        expected = {
            "status": "VALID",
            "scope": "SYNTHETIC_NATIVE_INTERFACE_ONLY",
            "strategy": request.plan.target,
            "timeframe": request.hypothesis_manifest.data_requirements.timeframe,
            "timezone": "UTC",
            "timestamp_column": False,
            "profile_file_modified": False,
            "historical_data_read": False,
            "backtests_executed": 0,
            "economic_assessment": "NOT_ASSESSED",
        }
        if not isinstance(report, dict) or any(report.get(k) != v for k, v in expected.items()):
            raise ValueError("Isolated native interface verification rejected")
        return checks, {
            "report": report,
            "process": result,
            "verification_sha256": self.fingerprint,
            "payload_sha256": digest(payload),
        }
