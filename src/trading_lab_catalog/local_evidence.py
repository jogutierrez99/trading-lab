"""Explicit trusted local locators, deliberately separate from agent responses."""

from pathlib import Path

from .read_api import CatalogReader, endpoint, identity
from .read_paths import pinned_catalogue
from .read_queries import Snapshot
from .store import Store


class LocalEvidenceReferences:
    """Operator-side opt-in. Returns locators, never opens their referenced files."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    _error = staticmethod(CatalogReader._error)

    @endpoint
    def for_run(self, run_id: str):
        rid = identity(run_id)
        with pinned_catalogue(self._path), Store(self._path).connection() as c:
            snap = Snapshot(c)
            run = snap.require("runs", rid)
            artifacts = snap.load("artifacts", snap.scoped_ids("artifacts", "run_id", rid))
            return {
                "api_version": "1.0",
                "status": "OK",
                "trusted_local_only": True,
                "run_id": rid,
                "evidence_reference": run["evidence_reference"],
                "artifacts": artifacts,
            }
