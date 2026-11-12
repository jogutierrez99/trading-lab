"""Operator plan, generated request and untrusted model delivery; versioned separately."""

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import HypothesisManifest, Identifier, Model, Text

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Target = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")]


class ImplementationPlan(Model):
    schema_version: Literal["1.0"]
    operation: Literal["NEW_STRATEGY", "NEW_EXPERIMENT"]
    target: Target
    specification_reviewed: Literal[True]
    review_note: Text
    max_wall_seconds: int = Field(ge=1, le=1800)
    check_timeout_seconds: int = Field(ge=1, le=120)

    def paths(self) -> list[str]:
        if self.operation == "NEW_STRATEGY":
            return [
                f"src/quant_lab/strategies/{self.target}.py",
                f"configs/strategies/{self.target}.yaml",
                f"tests/unit/test_{self.target}.py",
            ]
        return [f"configs/experiments/{self.target}.yaml", f"tests/unit/test_{self.target}.py"]

    def checks(self) -> list[list[str]]:
        python = [path for path in self.paths() if path.endswith(".py")]
        return [
            [
                "python",
                "-m",
                "pytest",
                f"tests/unit/test_{self.target}.py",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            ["python", "-m", "ruff", "check", "--no-cache", *python],
            ["python", "-m", "ruff", "format", "--check", "--no-cache", *python],
        ]


class ImplementationRequest(Model):
    schema_version: Literal["1.0"]
    mode: Literal["PREPARE_ONLY"]
    attempt_id: Identifier
    attempt_number: int
    task_id: Identifier
    candidate_id: Identifier
    hypothesis_manifest: HypothesisManifest
    hypothesis_sha256: Hash
    base_commit: Text
    branch: Text
    workspace: Text
    plan: ImplementationPlan
    allowed_write_paths: list[Text]
    protected_paths: list[Text]
    authorized_checks: list[list[str]]
    skill_paths: list[Text]
    previous_attempt: Text | None
    max_api_eur: None
    max_cpu_seconds: None
    native_interface_check: Literal["SYNTHETIC_OHLCV_UTC_V1"] | None = None


class DeliveredFile(Model):
    path: Text
    sha256: Hash

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
            raise ValueError("Delivery paths must be relative POSIX paths without escapes")
        if str(path) != value:
            raise ValueError("Non-canonical path")
        return value


class ModelDelivery(Model):
    schema_version: Literal["1.0"]
    candidate_id: Identifier
    task_id: Identifier
    attempt_id: Identifier
    hypothesis_sha256: Hash
    base_commit: Text
    branch: Text
    status: Literal["IMPLEMENTED", "BLOCKED"]
    summary: Text
    files: list[DeliveredFile]
    tests_run: Literal["NOT_RUN_BY_MODEL"]
    warnings: list[Text]
    blockers: list[Text]
    prepared_commands: list[list[Text]]

    @model_validator(mode="after")
    def consistent(self) -> "ModelDelivery":
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("Duplicate delivered paths")
        if self.status == "IMPLEMENTED" and (not self.files or self.blockers):
            raise ValueError("IMPLEMENTED requires files and no blockers")
        if self.status == "BLOCKED" and not self.blockers:
            raise ValueError("BLOCKED requires a reason")
        return self
