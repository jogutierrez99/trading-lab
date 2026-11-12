"""Versioned operator execution input and frozen deterministic runner request."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Identifier, Model, Text
from .implementation_contracts import Hash

GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class DatasetPin(Model):
    path: Text
    dataset_id: Hash
    manifest_sha256: Hash
    parquet_sha256: Hash
    kind: Literal["SYNTHETIC", "LOCAL_HISTORICAL"]
    provenance_note: Text
    provenance_files: dict[Text, Hash] = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute():
            raise ValueError("Dataset path must be absolute")
        return value


class RmmComparison(Model):
    task_id: Identifier
    candidate_id: Identifier
    hypothesis_sha256: Hash
    baseline_commit: GitCommit
    baseline_files: dict[Text, Hash]
    periods: tuple[Literal["train"], Literal["validation"]]


class ExecutionPlan(Model):
    schema_version: Literal["1.0"]
    experiment: Text
    experiment_sha256: Hash
    protocol: Literal["StudyBackend v1 / lab_experiment_v1"]
    scope: Literal["SYNTHETIC_TECHNICAL", "DECLARED_RESEARCH_PERIODS", "RMM_TRAIN_VALIDATION"]
    all_declared_periods_authorized: bool
    review_note: Text
    enable_execution_copy: bool
    datasets: list[DatasetPin] = Field(min_length=1, max_length=2)
    max_wall_seconds: int = Field(ge=1, le=3600)
    validation_timeout_seconds: int = Field(ge=1, le=300)
    max_backtests: int = Field(ge=1, le=100)
    max_candles: int = Field(ge=1, le=1000000)
    max_dataset_bytes: int = Field(ge=1, le=1000000000)
    comparison: RmmComparison | None = None

    @model_validator(mode="after")
    def comparison_scope(self):
        scoped = self.scope == "RMM_TRAIN_VALIDATION"
        if (
            scoped != (self.comparison is not None)
            or self.all_declared_periods_authorized == scoped
        ):
            raise ValueError(
                "RMM scope authorizes only the selected periods; ordinary scope requires all"
            )
        if scoped and self.max_backtests != 24:
            raise ValueError("RMM comparison requires exactly 24 BASE backtests")
        return self


class ExecutionRequest(Model):
    schema_version: Literal["1.0"]
    kind: Literal["BacktestExecutionRequest"]
    execution_id: Identifier
    task_id: Identifier
    candidate_id: Identifier
    implementation_id: Identifier
    implementation_receipt: Text
    implementation_receipt_sha256: Hash
    implementation_final_files: dict[Text, Hash]
    operator_format_repair: dict | None
    base_commit: Text
    implementation_request_sha256: Hash
    workspace: Text
    experiment: Text
    results: Text
    runner_entrypoint: Text
    runtime_files: dict[Text, Hash]
    input_files: dict[Text, Hash]
    plan: ExecutionPlan
    source_attempt_id: Identifier | None = None
    implementation_origin: Literal["CODEX_CLI", "MANUAL_TECHNICAL_REPAIR"] = "CODEX_CLI"
    source_implementation_receipt_sha256: Hash | None = None
