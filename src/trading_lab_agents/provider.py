"""A scripted in-process simulator. No credentials, transport, tools or real fallback."""

from threading import Lock
from typing import Literal, Protocol

from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import canonical


class ProposalProvider(Protocol):
    """Future adapters need a separate reviewed boundary; this is not authorization."""

    def respond(self, packet: bytes) -> bytes: ...


class SimulatedInterruption(KeyboardInterrupt):
    pass


class FakeProvider:
    version = "TLAgents.fake-researcher/1.0"

    def __init__(
        self,
        scenario: Literal[
            "valid",
            "none",
            "incomplete",
            "invented",
            "invalid",
            "truncated",
            "timeout",
            "malicious",
            "error",
            "interrupted",
            "false_oos",
        ] = "valid",
        *,
        response: bytes | None = None,
    ):
        if scenario not in {
            "valid",
            "none",
            "incomplete",
            "invented",
            "invalid",
            "truncated",
            "timeout",
            "malicious",
            "error",
            "interrupted",
            "false_oos",
        }:
            raise ValueError("Unknown simulated scenario")
        if response is not None and (type(response) is not bytes or len(response) > 64 * 1024):
            raise ValueError("Invalid simulated response")
        self._scenario, self._response = scenario, response
        self._calls, self._lock = 0, Lock()

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def respond(self, packet: bytes) -> bytes:
        data = parse(packet.decode("utf-8"))
        if data["mode"] != "SIMULATED" or data["tools"] != []:
            raise ValueError("Simulator has no tools or real-provider mode")
        with self._lock:
            self._calls += 1
        if self._scenario == "timeout":
            raise TimeoutError("Synthetic timeout after simulated reservation")
        if self._scenario == "interrupted":
            raise SimulatedInterruption("Synthetic process interruption")
        if self._scenario == "error":
            raise RuntimeError("Synthetic provider error")
        if self._response is not None:
            return self._response
        if self._scenario == "truncated":
            return b'{"schema_version":"1.0","candidates":['
        request, context = data["request"], data["catalogue"]
        # Cite a structural witness for each mandatory warning before filling the
        # bounded citation list. The host retains the complete provenance independently.
        references = context["references"]
        witnesses = []
        for warning in context.get("warning_provenance", []):
            keys = {(r["entity_type"], r["entity_id"]) for r in warning["origins"]}
            witness = next(
                (r for r in references if (r["entity_type"], r["entity_id"]) in keys), None
            )
            if witness is not None and witness not in witnesses:
                witnesses.append(witness)
        citations = (witnesses + [r for r in references if r not in witnesses])[:20]
        result = {
            "schema_version": "1.0",
            "contract_kind": "ResearchHypothesis",
            "request_id": request["request_id"],
            "status": "HYPOTHESIS_PROPOSED",
            "candidates": [],
            "rejected_reasons": [],
            "missing_fields": [],
            "notes": None,
        }
        if self._scenario == "none" or context["match_status"] == "EXACT_MATCH":
            result.update(
                status="NO_HYPOTHESIS",
                rejected_reasons=[
                    "No defensible new hypothesis; inspect the supplied antecedent references"
                ],
            )
        elif self._scenario == "incomplete":
            result.update(status="NEEDS_REVIEW", missing_fields=["Independent source statistics"])
        else:
            market = request["market"]
            result["candidates"] = [
                {
                    "hypothesis_id": "simulated_hypothesis_01",
                    "asset": market["asset"],
                    "market_type": market["market_type"],
                    "timeframe": market["timeframe"],
                    "statement": "A causal prior-high breakout might persist after costs; untested",
                    "justification": (
                        "Synthetic proposed persistence mechanism, not an observed edge"
                    ),
                    "source_ids": [request["source_refs"][0]["reference_id"]],
                    "evidence_ids": [],
                    "observable_conditions": ["Closed candle exceeds a previously available high"],
                    "falsification": ["Reject if preregistered net expectancy is nonpositive"],
                    "bias_risks": ["Selection and multiple-testing uncertainty"],
                    "limitations": context["limitations"],
                    "catalog_refs": citations,
                    "verification_status": "DECLARED",
                }
            ]
        if self._scenario == "invented" and result["candidates"]:
            result["candidates"][0]["source_ids"] = ["invented_source"]
        if self._scenario == "false_oos" and result["candidates"]:
            result["candidates"][0]["statement"] = (
                "Independent OOS validated; guaranteed future profit"
            )
        if self._scenario == "invalid":
            result["status"] = "TRADING_APPROVED"
        if self._scenario == "malicious":
            result["grant"] = {"execute": True, "send": True, "budget": 2000}
        return canonical(result).encode("utf-8")
