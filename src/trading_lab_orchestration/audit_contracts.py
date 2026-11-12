"""Strict, versioned audit contracts; economic conclusions never grant permissions."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Identifier, Model, Text

SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class AuditRequest(Model):
    schema_version: Literal["1.0"] = "1.0"
    auditor_profile: Literal["quant_auditor_v1"] = "quant_auditor_v1"
    auditor_version: Literal["1.0"] = "1.0"
    review_mode: Literal["DETERMINISTIC_ONLY", "MODEL_ASSISTED"] = "DETERMINISTIC_ONLY"
    audit_id: Identifier | None = None
    task_id: Identifier
    candidate_id: Identifier
    implementation_id: Identifier
    execution_id: Identifier
    experiment_id: Identifier
    run_id: Identifier
    execution_receipt: Text
    execution_receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    protocol: Literal["StudyBackend v1 / lab_experiment_v1"] = "StudyBackend v1 / lab_experiment_v1"
    resolved_configuration_sha256: SHA
    dataset_manifest_sha256: dict[str, SHA] = Field(min_length=1, max_length=100)
    max_files: int = Field(default=5000, ge=1, le=10000)
    max_total_bytes: int = Field(default=64000000, ge=1, le=128000000)
    review_revision: int = Field(default=1, ge=1, le=100)
    review_reason: Text | None = None

    @model_validator(mode="after")
    def exact_identity(self):
        if self.review_revision > 1 and not self.review_reason:
            raise ValueError("A new audit revision requires an explicit review reason")
        if any(
            getattr(self, k).lower() == "latest"
            for k in (
                "task_id",
                "candidate_id",
                "implementation_id",
                "execution_id",
                "experiment_id",
                "run_id",
            )
        ):
            raise ValueError("Exact identities required; latest is forbidden")
        return self


class EvidenceRef(Model):
    path: Text
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Gate(Model):
    status: Text
    findings: list[Text]
    references: list[str]


class AuditVerdict(Model):
    schema_version: Literal["1.0"] = "1.0"
    audit_id: Identifier
    audit_task_id: Identifier
    task_id: Identifier
    candidate_id: Identifier
    implementation_id: Identifier
    execution_id: Identifier
    experiment_id: Identifier
    run_id: Identifier
    auditor_profile: Literal["quant_auditor_v1"] = "quant_auditor_v1"
    auditor_version: Literal["1.0"] = "1.0"
    effective_review_mode: Literal["DETERMINISTIC_ONLY", "MODEL_ASSISTED"]
    audit_timestamp_utc: Text
    audit_status: Literal["COMPLETED_WITH_LIMITATIONS", "BLOCKED_EVIDENCE", "FAILED"]
    gates: dict[Literal["A", "B", "C", "D"], Gate]
    auditor_verdict: Literal["NO_DECISION"]
    original_classifications: list[dict]
    observations: dict
    references: dict[str, EvidenceRef]
    blockers: list[Text]
    uncertainties: list[Text]
    recommended_next_test: Text
    scope_of_verification: list[Text]
    api_cost_measured_eur: float | None = None
    api_cost_provenance: Text | None = None
    consumption: dict = Field(
        default_factory=lambda: {
            "cpu_seconds": None,
            "peak_memory_bytes": None,
            "api_input_tokens": None,
            "api_output_tokens": None,
            "note": "Not measured; no model call in deterministic mode",
        }
    )
    model_executed: bool = False
    economic_validation: Literal[False] = False
    human_paper_review_eligible: Literal[False] = False
    audit_activated_paper: Literal[False] = False
    demo_orders_sent: Literal[False] = False
    live_orders_sent: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self):
        if set(self.gates) != {"A", "B", "C", "D"}:
            raise ValueError("All four gates are required")
        allowed = {
            "A": {"INTEGRITY_OK", "INTEGRITY_FAIL"},
            "B": {"DESIGN_LIMITED", "NOT_VERIFIABLE"},
            "C": {"INSUFFICIENT_EVIDENCE"},
            "D": {"NOT_READY"},
        }
        if any(g.status not in allowed[k] for k, g in self.gates.items()):
            raise ValueError("Gate status outside implemented audit profile")
        if (self.effective_review_mode == "MODEL_ASSISTED") != self.model_executed:
            raise ValueError("Effective mode must describe actual execution")
        for gate in self.gates.values():
            if not set(gate.references) <= self.references.keys():
                raise ValueError("Invented evidence reference")
        return self


class ModelReview(Model):
    """Supplement only: cannot change gates, classifications, trading or verdict."""

    schema_version: Literal["1.0"] = "1.0"
    findings: list[Text] = Field(max_length=20)
    evidence_references: list[str] = Field(min_length=1, max_length=50)
    uncertainties: list[Text] = Field(max_length=20)
    verdict: Literal["NO_DECISION"]
    demo_authorized: Literal[False]
