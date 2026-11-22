"""Explicit fake validator: bytes in/out, no tools, clients, keys or fallback."""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock

from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import canonical


class FakeValidatorProvider:
    version = "TLAgents.fake_validator/1.0"

    def __init__(self, *, scenario="valid", response: bytes | None = None):
        if scenario not in {
            "valid",
            "invented_reference",
            "invented_metric",
            "promote",
            "drop_limitation",
            "truncated",
            "timeout",
            "error",
            "interrupted",
            "malicious",
        }:
            raise ValueError("Unknown fake scenario")
        if response is not None and (type(response) is not bytes or len(response) > 32 * 1024 + 1):
            raise ValueError("Bounded simulated response required")
        self._scenario, self._response, self._calls = scenario, response, 0
        self._lock = Lock()
        self._observation = ContextVar("fake_validator_invocation", default=None)

    @contextmanager
    def observing(self, observation: dict):
        """Private host trace, isolated across threads/books; never provider input."""
        token = self._observation.set(observation)
        try:
            yield
        finally:
            self._observation.reset(token)

    @property
    def calls(self):
        with self._lock:
            return self._calls

    def respond(self, raw: bytes) -> bytes:
        with self._lock:
            observation = self._observation.get()
            if observation is not None:
                observation["observed_calls"] += 1
            self._calls += 1
        packet = parse(raw)
        if packet["mode"] != "SIMULATED" or packet["tools"] != []:
            raise ValueError("Fake-only invocation")
        if self._scenario == "timeout":
            raise TimeoutError("Synthetic provider timeout")
        if self._scenario == "error":
            raise RuntimeError("Synthetic provider error")
        if self._scenario == "interrupted":
            raise KeyboardInterrupt("Synthetic interruption")
        if self._response is not None:
            return self._response
        if self._scenario == "truncated":
            return b'{"schema_version":"1.0"'
        policy = packet["policy"]
        result = {
            "schema_version": "1.0",
            "contract_kind": "ValidationAssessment",
            "request_id": packet["request"]["request_id"],
            "agent_role": "validator",
            "status": "NEEDS_REVIEW" if policy["needs_review"] else "CONSULTATIVE",
            "source_run_ids": packet["request"]["source_run_ids"],
            "model_review": {
                "schema_version": "1.0",
                "findings": policy["allowed_findings"][:20],
                "evidence_references": [
                    r["reference_id"] for r in packet["catalogue"]["references"]
                ],
                "uncertainties": [o["text"] for o in policy["obligations"]],
                "verdict": "NO_DECISION",
                "demo_authorized": False,
            },
            "recommendation": "REQUEST_MORE_EVIDENCE",
            "limitations": [o["text"] for o in policy["obligations"]],
            "does_not_override_source": True,
            "notes": None,
        }
        if self._scenario == "invented_reference":
            result["model_review"]["evidence_references"] = ["invented"]
        if self._scenario == "invented_metric":
            result["model_review"]["findings"] = ["Guaranteed profit; p_value=0.01"]
        if self._scenario == "promote":
            result["model_review"]["demo_authorized"] = True
        if self._scenario == "drop_limitation":
            result["limitations"] = []
        if self._scenario == "malicious":
            result["tools"] = ["execute"]
        return canonical(result).encode()
