"""Consultative TLAgents contract. Existing ModelReview is reused unchanged."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from trading_lab_orchestration.audit_contracts import ModelReview

from .models import ID, SHA, CatalogID, Contract, Text, Texts

VALIDATOR_VERSION = "TLAgents.validator/1.0"
OUTPUT_LIMIT = 32 * 1024


class ValidationAssessment(Contract):
    schema_version: Literal["1.0"]
    contract_kind: Literal["ValidationAssessment"]
    request_id: ID
    agent_role: Literal["validator", "coordinator_advisory"]
    status: Literal["CONSULTATIVE", "NEEDS_REVIEW"]
    source_run_ids: Annotated[list[CatalogID], Field(max_length=4)]
    model_review: ModelReview
    recommendation: Literal[
        "NO_DECISION", "REQUEST_MORE_EVIDENCE", "CONTINUE_RESEARCH", "DO_NOT_ADVANCE"
    ]
    limitations: Texts
    does_not_override_source: Literal[True]
    notes: Text | None = None

    @field_validator("does_not_override_source", mode="before")
    @classmethod
    def real_true(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("An explicit true invariant is required")
        return value

    @field_validator("model_review", mode="before")
    @classmethod
    def no_numeric_authorization(cls, value):
        # Literal[False] in the historic model also accepts numeric zero. The new
        # boundary is stricter without changing that historical model's contract.
        if isinstance(value, dict) and type(value.get("demo_authorized")) is not bool:
            raise ValueError("Explicit false required")
        return value

    @model_validator(mode="after")
    def source_identity(self) -> Self:
        if len(self.source_run_ids) != len(set(self.source_run_ids)):
            raise ValueError("Duplicate run identity")
        if self.status == "CONSULTATIVE" and not self.source_run_ids:
            raise ValueError("A consultative result requires a run")
        return self


class AuditAnchor(Contract):
    run_id: CatalogID
    audit_id: ID
    verdict_sha256: SHA


class ValidationRequest(Contract):
    """Host simulation input; not a coordinator task, permission or source seal."""

    schema_version: Literal["1.0"]
    contract_kind: Literal["ValidationRequest"]
    request_id: ID
    source_run_ids: Annotated[list[CatalogID], Field(min_length=1, max_length=4)]
    audits: Annotated[list[AuditAnchor], Field(min_length=1, max_length=4)]
    expected_checkpoint: SHA | None

    @model_validator(mode="after")
    def anchors(self) -> Self:
        runs = self.source_run_ids
        if len(runs) != len(set(runs)) or any(s.casefold() == "latest" for s in runs):
            raise ValueError("Exact distinct runs required")
        if len({a.audit_id for a in self.audits}) != len(self.audits):
            raise ValueError("Duplicate audit identity")
        if sorted(a.run_id for a in self.audits) != sorted(runs):
            raise ValueError("Exactly one audit anchor per run required")
        return self
