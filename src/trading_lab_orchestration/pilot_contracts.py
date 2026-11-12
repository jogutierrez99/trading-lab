"""Step 4.5 is a verification result, never another operational state machine."""

from typing import Literal

from pydantic import Field, model_validator

from .audit_contracts import SHA, EvidenceRef
from .contracts import Identifier, Model, Text


class PilotVerificationRequest(Model):
    schema_version: Literal["1.0"] = "1.0"
    task_id: Identifier
    implementation_id: Identifier
    execution_id: Identifier
    run_id: Identifier
    audit_id: Identifier
    notification_id: Identifier
    strategy: Identifier
    strategy_version: Text
    telegram_receipt: Text
    telegram_receipt_sha256: SHA
    expected_message_id: int = Field(gt=0)
    expected_send_attempts: int = Field(default=1, ge=1, le=3)
    expected_backtests: int = Field(default=3, ge=1, le=100)
    expected_closed_trades_per_case: int = Field(default=0, ge=0)
    max_files: int = Field(default=5000, ge=1, le=10000)
    max_total_bytes: int = Field(default=64000000, ge=1, le=128000000)

    @model_validator(mode="after")
    def exact_identities(self):
        for name in (
            "task_id",
            "implementation_id",
            "execution_id",
            "run_id",
            "audit_id",
            "notification_id",
        ):
            if getattr(self, name).lower() == "latest":
                raise ValueError("Exact pilot identities required; latest is forbidden")
        return self


class VerificationStage(Model):
    identity: Text
    historical_state: Text | None = None
    status: Literal["VERIFIED", "MISSING_EVIDENCE", "CONTRADICTION", "NOT_CHECKED"]
    evidence: list[Text] = Field(default_factory=list)
    manual_intervention: list[Text] = Field(default_factory=list)
    limitations: list[Text] = Field(default_factory=list)


class PilotVerificationResult(Model):
    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["HistoricalPilotVerification"] = "HistoricalPilotVerification"
    verification_id: Identifier
    verified_at_utc: Text
    status: Literal["VERIFIED_HISTORICAL_TECHNICAL_PILOT", "BLOCKED"]
    request: PilotVerificationRequest
    candidate_id: Identifier | None = None
    hypothesis_id: Identifier | None = None
    experiment_id: Identifier | None = None
    database: dict
    protected_roots: list[Text]
    export_safe: bool
    stages: dict[str, VerificationStage]
    references: dict[str, EvidenceRef]
    observations: dict = Field(default_factory=dict)
    limitations: list[Text]
    actions_pending: list[Text]
    historical_reconstruction: Literal[True] = True
    new_end_to_end_execution: Literal[False] = False
    unattended_automation: Literal[False] = False
    model_auditor_deployed: Literal[False] = False
    economic_validation: Literal[False] = False
    demo_authorized: Literal[False] = False
