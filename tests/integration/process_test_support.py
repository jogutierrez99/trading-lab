"""Keep our Windows child handles for deterministic fixture lifetimes.

Access-denied PID reuse is legitimately UNKNOWN. Happy-path tests must not depend
on Windows assigning an exited fixture's PID to a protected service mid-assertion.
Reuse/denial are exercised explicitly through controlled probes instead.
"""

import os
import subprocess

import pytest


@pytest.fixture
def retain_windows_processes(monkeypatch):
    children = []
    original = subprocess.Popen

    def owned_child(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)  # Retains its original kernel handle after wait().
        return child

    if os.name == "nt":
        monkeypatch.setattr(subprocess, "Popen", owned_child)
    yield
    children.clear()  # Handles only; never signal or terminate by PID.
