"""Only local CLI authentication. Probes do not start model sessions."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from .processes import safe_environment

REQUIRED_FLAGS = (
    "--json",
    "--output-schema",
    "--output-last-message",
    "--sandbox",
    "--ignore-user-config",
    "--ephemeral",
)


class PreflightError(ValueError):
    pass


class CodexCLI:
    def __init__(self, executable: str | list[str] = "codex", *, windows_sandbox="elevated"):
        if windows_sandbox not in {"elevated", "mxc"}:
            raise PreflightError("Windows sandbox must be elevated or mxc")
        if windows_sandbox == "mxc" and os.name != "nt":
            raise PreflightError("MXC is available only on Windows")
        self.windows_sandbox = windows_sandbox
        # A directly spawned CLI has no desktop app package identity. Keep the
        # configured Windows sandbox and drop only the desktop launcher request.
        self.omit_env = ("CODEX_WINDOWS_REGISTERED_CORE",) if os.name == "nt" else ()
        prefix = [executable] if isinstance(executable, str) else executable
        found = shutil.which(prefix[0])
        if not found:
            raise PreflightError("Codex executable missing; install/configure Codex CLI explicitly")
        self.executable = str(Path(found).resolve())
        self.command = [self.executable, *prefix[1:]]
        if Path(found).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            raise PreflightError("Use a native executable, not a shell wrapper (.cmd/.bat/.ps1)")

    def probe(self, cwd: Path) -> dict:
        def call(args: list[str]) -> subprocess.CompletedProcess:
            try:
                return subprocess.run(
                    [*self.command, *args],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    env=safe_environment(cwd, omit=self.omit_env),
                    shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PreflightError("Cannot run bounded local Codex capability probe") from exc

        version = call(["--version"])
        help_ = call(["exec", "--help"])
        if (
            version.returncode
            or help_.returncode
            or any(flag not in help_.stdout for flag in REQUIRED_FLAGS)
        ):
            raise PreflightError("Installed Codex CLI does not support required safe exec flags")
        login = call(["login", "status"])
        # Never store/print authentication command stdout/stderr; it may include account details.
        if login.returncode:
            raise PreflightError("Codex local authentication unavailable; run codex login manually")
        return {
            "executable": self.executable,
            "version": version.stdout.strip(),
            "authenticated": True,
            "exec_help": help_.stdout,
        }

    def argv(self, workspace: Path, schema: Path, delivery: Path) -> list[str]:
        # --ignore-user-config also drops the native Windows backend selector.
        # Restore the restricted-account sandbox explicitly; never use unelevated/full access.
        platform_options = (
            ["-c", f'windows.sandbox="{self.windows_sandbox}"'] if os.name == "nt" else []
        )
        return [
            *self.command,
            "--no-daemon",
            "-a",
            "never",
            "exec",
            "--ignore-user-config",
            "--sandbox",
            "workspace-write",
            "-c",
            'default_permissions=":workspace"',
            "-c",
            "sandbox_workspace_write.network_access=false",
            *platform_options,
            "--ephemeral",
            "--json",
            "--color",
            "never",
            "--cd",
            str(workspace),
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(delivery),
            "-",
        ]


def usage(path: Path) -> dict | None:
    """Record reported units verbatim; no conversion into money or credits."""
    result = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            result = event["usage"]
    return result
