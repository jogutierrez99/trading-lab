"""Real Git checkout with paths beyond legacy Windows MAX_PATH."""

from trading_lab_orchestration.workspaces import create_workspace, git


def test_worktree_long_paths_without_changing_repository_configuration(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.longpaths", "false")
    relative = "/".join(["research_results"] + ["frozen_evidence_" + str(i) * 18 for i in range(5)])
    source = repo / relative / "original.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"immutable": true}', encoding="utf-8")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "base",
    )
    # Keep the worktree root itself short: this regression concerns tracked
    # checkout paths, not Git's separate limit for its administrative directory.
    workspace = tmp_path / ("isolated_" * 3) / "workspace"
    assert len(str(workspace / relative / "original.json")) > 260
    git(repo, "worktree", "add", "-b", "codex/long-path-test", str(workspace))
    assert (workspace / relative / "original.json").read_bytes() == source.read_bytes()
    assert git(repo, "config", "--local", "--get", "core.longpaths") == "false"
    assert not git(workspace, "status", "--porcelain")


def test_deep_worktree_root_materializes_from_inside_new_checkout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.longpaths", "false")
    (repo / "evidence.txt").write_text("base", encoding="utf-8")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "base",
    )
    head = git(repo, "rev-parse", "HEAD")
    (repo / "evidence.txt").write_text("operator edit", encoding="utf-8")
    depth = max(32, 226 - len(str(tmp_path)))
    root = tmp_path / ("a" * depth) / "attempt"
    root.mkdir(parents=True)
    workspace = root / "workspace"
    create_workspace(
        {
            "repo": str(repo),
            "workspace": str(workspace),
            "root": str(root),
            "branch": "codex/deep-fixture",
            "base_commit": head,
        },
        [],
    )
    assert (workspace / "evidence.txt").read_text(encoding="utf-8") == "base"
    assert (repo / "evidence.txt").read_text(encoding="utf-8") == "operator edit"
    assert git(repo, "config", "--local", "--get", "core.longpaths") == "false"
    assert not git(workspace, "status", "--porcelain")
