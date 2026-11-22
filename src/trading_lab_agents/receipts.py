"""Disposable in-memory receipts. No filesystem writes, SQLite or operational queue."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock

from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.contracts import canonical

from .context import ResearchError


@dataclass
class _Entry:
    admission_sha256: str
    request_bytes: bytes
    context_bytes: bytes | None = None
    response_bytes: bytes | None = None
    result_bytes: bytes | None = None
    history: list[dict] = field(default_factory=lambda: [{"state": "PREPARING"}])


class ReceiptBook:
    """Share one book between readers. Guarantees are in-process, not crash durable.

    The lock spans the bounded simulation, preventing two callers from performing
    the same invocation. Results are held as immutable canonical bytes, and every
    retrieval/export returns a detached value. Export is data, never a write tool.
    """

    def __init__(self, *, max_entries: int = 64):
        if type(max_entries) is not int or not 1 <= max_entries <= 256:
            raise ValueError("Invalid disposable receipt limit")
        self._max_entries = max_entries
        self._entries, self._lock = {}, RLock()

    @contextmanager
    def claim(self, request_id: str, admission_sha256: str, request_bytes: bytes):
        with self._lock:
            entry = self._entries.get(request_id)
            new = entry is None
            if new:
                if len(self._entries) >= self._max_entries:
                    raise ResearchError("RECEIPT_LIMIT_EXCEEDED")
                entry = _Entry(admission_sha256, request_bytes)
                self._entries[request_id] = entry
            elif entry.admission_sha256 != admission_sha256:
                entry.history.append({"state": "CONFLICT", "admission_sha256": admission_sha256})
                raise ResearchError("CONFLICT")
            yield entry, new

    @staticmethod
    def finish(entry: _Entry, result: dict) -> dict:
        if entry.result_bytes is not None:
            raise ResearchError("RECEIPT_ALREADY_FINAL")
        result["receipt"]["request_bytes_sha256"] = sha(entry.request_bytes)
        entry.history.append({"state": result["status"], "error_code": result["error_code"]})
        entry.result_bytes = canonical(result).encode("utf-8")
        return parse(entry.result_bytes)

    def export(self, request_id: str) -> dict:
        with self._lock:
            entry = self._entries.get(request_id)
            if entry is None:
                raise ResearchError("NOT_FOUND")
            return parse(
                canonical(
                    {
                        "scope": "DISPOSABLE_SIMULATION_MEMORY_ONLY",
                        "admission_sha256": entry.admission_sha256,
                        "request_hex": entry.request_bytes.hex(),
                        "context_hex": entry.context_bytes.hex() if entry.context_bytes else None,
                        "response_hex": entry.response_bytes.hex()
                        if entry.response_bytes
                        else None,
                        "result": parse(entry.result_bytes) if entry.result_bytes else None,
                        "history": entry.history,
                    }
                )
            )
