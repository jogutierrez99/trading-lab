"""Deterministic fake only. No key loading, clients, tools or real fallback."""

from threading import Lock

from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import canonical

from .designer_models import SPEC_LIMIT


class FakeDesignerProvider:
    version = "TLAgents.fake_designer/1.0"

    def __init__(self, response: bytes | None = None, *, scenario: str = "response"):
        if response is not None and (type(response) is not bytes or len(response) > SPEC_LIMIT + 1):
            raise ValueError("Bounded synthetic response required")
        if scenario not in {
            "response",
            "incomplete",
            "truncated",
            "timeout",
            "error",
            "interrupted",
            "malicious",
        }:
            raise ValueError("Unknown fake scenario")
        self._response, self._scenario, self._calls = response, scenario, 0
        self._lock = Lock()

    @property
    def calls(self):
        with self._lock:
            return self._calls

    def respond(self, packet: bytes) -> bytes:
        with self._lock:
            self._calls += 1
        data = parse(packet)
        if data["mode"] != "SIMULATED" or data["tools"] != []:
            raise ValueError("Invalid fake invocation")
        if self._scenario == "timeout":
            raise TimeoutError("Synthetic timeout")
        if self._scenario == "error":
            raise RuntimeError("Synthetic provider error")
        if self._scenario == "interrupted":
            raise KeyboardInterrupt("Synthetic interruption")
        if self._scenario == "truncated":
            return b'{"schema_version":"1.0"'
        if self._scenario == "malicious":
            return b'{"specification_reviewed":true,"command":"execute"}'
        if self._scenario == "incomplete" or self._response is None:
            return canonical(
                {
                    "schema_version": "1.0",
                    "contract_kind": "StrategySpecification",
                    "request_id": data["request"]["request_id"],
                    "research_hypothesis_id": data["candidate"]["hypothesis_id"],
                    "status": "NEEDS_REVIEW",
                    "manifest": None,
                    "capital_policy": "UNKNOWN",
                    "formulas": [],
                    "risk_constraints": None,
                    "cost_scenarios": [],
                    "capability_reference_ids": [],
                    "implementation_operation": "UNSUPPORTED",
                    "missing_fields": ["Scientific rules not supplied"],
                    "review_requirements": [],
                    "notes": None,
                }
            ).encode()
        return self._response
