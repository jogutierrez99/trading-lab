"""New worktrees only; compare all working files against the immutable base snapshot."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .contracts import canonical


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.longpaths=true",
            "-C",
            str(repo),
            *args,
        ],
        capture_output=True,
        timeout=30,
        shell=False,
    )
    if result.returncode:
        raise ValueError("git failed: " + result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8", errors="strict").strip()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(canonical(value))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(workspace: Path) -> dict[str, str]:
    result = {}
    for directory, dirs, files in os.walk(workspace, followlinks=False):
        parent = Path(directory)
        for name in list(dirs):
            child = parent / name
            if child.is_symlink() or child.is_junction():
                raise ValueError(f"Linked directory forbidden: {child.relative_to(workspace)}")
            if name in {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}:
                dirs.remove(name)
        for name in files:
            child = parent / name
            if child.is_symlink():
                raise ValueError(f"Linked file forbidden: {child.relative_to(workspace)}")
            result[child.relative_to(workspace).as_posix()] = file_hash(child)
    return result


def changes(attempt: dict) -> dict[str, str | None]:
    root, workspace = Path(attempt["root"]), Path(attempt["workspace"])
    before = json.loads((root / "baseline.json").read_text(encoding="utf-8"))
    after = inventory(workspace)
    if git(workspace, "rev-parse", "HEAD") != attempt["base_commit"]:
        raise ValueError("HEAD changed; commits are not allowed during implementation")
    if git(workspace, "branch", "--show-current") != attempt["branch"]:
        raise ValueError("Workspace branch changed")
    return {
        name: after.get(name)
        for name in set(before) | set(after)
        if before.get(name) != after.get(name)
    }


def create_workspace(attempt: dict, allowed: list[str]) -> None:
    repo, workspace = Path(attempt["repo"]), Path(attempt["workspace"])
    if workspace.exists():
        raise ValueError("Workspace already exists; refusing ambiguous directory")
    for name in allowed:
        if git(repo, "ls-tree", "--name-only", attempt["base_commit"], "--", name):
            raise ValueError(f"Target already exists at base commit: {name}")
        if (repo / name).exists():
            raise ValueError(f"Target collides with user working files: {name}")
    # No checkout/reset/stash of the user's working tree. No commits, cleanup or push.
    options = ("--no-checkout",) if os.name == "nt" else ()
    git(
        repo,
        "worktree",
        "add",
        *options,
        "-b",
        attempt["branch"],
        str(workspace),
        attempt["base_commit"],
    )
    if options:
        # Git for Windows' child checkout can reject a deep absolute GIT_DIR even
        # with core.longpaths enabled. Discover .git from the new worktree instead.
        if git(workspace, "rev-parse", "HEAD") != attempt["base_commit"]:
            raise ValueError("New worktree does not point to the frozen base")
        git(workspace, "read-tree", "--reset", "-u", "HEAD")
    write_json(Path(attempt["root"]) / "baseline.json", inventory(workspace))
