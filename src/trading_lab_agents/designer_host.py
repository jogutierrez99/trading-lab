"""In-process synthetic handoff review. Not an operational authorization service."""

from threading import RLock

from trading_lab_catalog.read_models import public_data
from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.contracts import canonical

from .context import ResearchError
from .designer_capabilities import DesignCapabilities
from .models import INPUT_LIMIT, OUTPUT_LIMIT, ResearchHypothesis, ResearchRequest, decode, identity
from .receipts import ReceiptBook


class DesignReviewHost:
    """Only the host can issue a local design review from a recoverable fake receipt.

    A reference must exist in this registry and bind the original byte identities.
    Provider declarations/booleans are never admitted. No persistence, real permits,
    candidate registration or execution permission is provided by this component.
    The embedding Python host is trusted, as with the existing ReceiptBook.
    """

    def __init__(self):
        self._reviews = {}
        self._lock = RLock()

    def review(
        self,
        request_bytes: bytes,
        hypothesis_bytes: bytes,
        candidate_id: str,
        *,
        researcher_receipts: ReceiptBook,
        capabilities: DesignCapabilities,
        reuse: dict | None = None,
    ) -> str:
        if (
            type(researcher_receipts) is not ReceiptBook
            or type(capabilities) is not DesignCapabilities
        ):
            raise TypeError("Explicit synthetic host components required")
        request = decode(request_bytes, ResearchRequest, INPUT_LIMIT)
        hypothesis = decode(hypothesis_bytes, ResearchHypothesis, OUTPUT_LIMIT)
        receipt = researcher_receipts.export(request.request_id)
        result = receipt["result"]
        if (
            request.status != "PREPARED"
            or hypothesis.status != "HYPOTHESIS_PROPOSED"
            or hypothesis.request_id != request.request_id
            or result is None
            or result["status"] != "COMPLETE"
            or result["mode"] != "SIMULATED"
            or result["hypothesis"] != hypothesis.model_dump(mode="json")
            or receipt["request_hex"] != request_bytes.hex()
            or receipt["response_hex"] != hypothesis_bytes.hex()
            or result["receipt"]["response_sha256"] != sha(hypothesis_bytes)
        ):
            raise ResearchError("HANDOFF_NOT_REVIEWABLE")
        candidates = [c for c in hypothesis.candidates if c.hypothesis_id == candidate_id]
        if len(candidates) != 1:
            raise ResearchError("CANDIDATE_NOT_FOUND")
        candidate = candidates[0]
        expected_fingerprint = identity(
            "HypothesisDraft",
            {"request_id": request.request_id, "candidate": candidate.model_dump(mode="json")},
        )
        details = result["receipt"]
        if (
            details["agent_id"] != "quant_researcher_v1"
            or details["scope"] != "IN_PROCESS_SIMULATION_ONLY"
            or details["request_bytes_sha256"] != sha(request_bytes)
            or details["hypothesis_fingerprint"]
            != identity("ResearchHypothesis", hypothesis.model_dump(mode="json"))
            or {"hypothesis_id": candidate_id, "fingerprint": expected_fingerprint}
            not in details["candidate_fingerprints"]
        ):
            raise ResearchError("HANDOFF_FINGERPRINT_MISMATCH")
        if (candidate.asset, candidate.market_type, candidate.timeframe) != (
            request.market.asset,
            request.market.market_type,
            request.market.timeframe,
        ):
            raise ResearchError("HANDOFF_MARKET_MISMATCH")
        provenance = result["antecedents"]["warning_provenance"]
        if any(w["warning"] not in candidate.limitations for w in provenance):
            raise ResearchError("HANDOFF_LIMITATION_DROPPED")
        if reuse is not None:
            if type(reuse) is not dict or set(reuse) != {
                "version_id",
                "code_sha256",
                "configuration_sha256",
                "signal_template",
            }:
                raise ResearchError("REUSE_WITNESS_INVALID")
            from pydantic import TypeAdapter

            from .models import SHA, CatalogID

            TypeAdapter(CatalogID).validate_python(reuse["version_id"], strict=True)
            for field in ("code_sha256", "configuration_sha256"):
                TypeAdapter(SHA).validate_python(reuse[field], strict=True)
            if type(reuse["signal_template"]) is not dict:
                raise ResearchError("REUSE_WITNESS_INVALID")
        payload = {
            "mode": "SIMULATED_DESIGN_REVIEW_ONLY",
            "request_sha256": sha(request_bytes),
            "hypothesis_sha256": sha(hypothesis_bytes),
            "request_id": request.request_id,
            "candidate_id": candidate_id,
            "candidate_fingerprint": expected_fingerprint,
            "capability_fingerprint": capabilities.fingerprint,
            "research_checkpoint": result["antecedents"]["checkpoint"],
            "warning_provenance": provenance,
            "limitations": list(candidate.limitations),
            "references": [r.model_dump(mode="json") for r in candidate.catalog_refs],
            "reuse": reuse,
            "authorizes": "SYNTHETIC_DESIGN_ONLY_NO_IMPLEMENTATION_OR_EXECUTION",
        }
        if public_data(payload) != payload or len(canonical(payload).encode()) > 32 * 1024:
            raise ResearchError("REVIEW_CONTEXT_INVALID")
        reference = identity("SyntheticDesignReview", payload)
        with self._lock:
            if len(self._reviews) >= 64 and reference not in self._reviews:
                raise ResearchError("REVIEW_LIMIT_EXCEEDED")
            self._reviews[reference] = canonical(payload).encode()
        return reference

    def resolve(
        self,
        reference: str,
        request_bytes: bytes,
        hypothesis_bytes: bytes,
        candidate_id: str,
        capabilities: DesignCapabilities,
    ) -> dict:
        with self._lock:
            if type(reference) is not str or reference not in self._reviews:
                raise ResearchError("HOST_REVIEW_REQUIRED")
            payload = parse(self._reviews[reference])
        if (
            payload["request_sha256"],
            payload["hypothesis_sha256"],
            payload["candidate_id"],
            payload["capability_fingerprint"],
        ) != (sha(request_bytes), sha(hypothesis_bytes), candidate_id, capabilities.fingerprint):
            raise ResearchError("HOST_REVIEW_IDENTITY_MISMATCH")
        return payload
