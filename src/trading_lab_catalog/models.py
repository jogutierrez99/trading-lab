"""Versioned catalogue contracts. Percentage fields retain percentage units."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from pydantic_core import to_jsonable_python

Key = Annotated[str, Field(min_length=1, max_length=160)]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Number = Annotated[float, Field(allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*")
    @classmethod
    def finite_json(cls, value):
        if isinstance(value, (dict, list)):
            canonical(to_jsonable_python(value))
        return value

    @field_validator("created_at_utc", "started_at_utc", "finished_at_utc", check_fields=False)
    @classmethod
    def utc_timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value).utcoffset() != UTC.utcoffset(None):
            raise ValueError("Timestamp must be timezone-aware UTC")
        return value


class Strategy(Model):
    id: Key
    name: str
    family: str | None = None
    description: str
    source: str
    created_at_utc: str | None = None


class Version(Model):
    id: Key
    strategy_id: Key
    semantic_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")] | None
    implementation_reference: str
    git_commit: str | None = None
    code_sha256: Hash
    configuration_sha256: Hash | None = None
    parameter_schema: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class Experiment(Model):
    id: Key
    version_id: Key
    hypothesis: str
    market_type: str
    asset: str
    timeframe: str
    direction: str
    parameters: dict[str, JsonValue]
    parameter_fingerprint: Hash | None = None
    configuration_sha256: Hash
    dataset_sha256: Hash
    experimental_protocol: str
    risk: dict[str, JsonValue]
    execution_assumptions: dict[str, JsonValue]
    holdout: Literal["CONSUMED", "UNOBSERVED", "UNKNOWN"]
    capital_policy: Literal["RESET_PER_SEGMENT", "CONTINUOUS", "UNKNOWN"]

    @model_validator(mode="after")
    def parameters_identity(self):
        expected = fingerprint(self.parameters)
        if self.parameter_fingerprint is not None and self.parameter_fingerprint != expected:
            raise ValueError("Parameter fingerprint differs from parameters")
        object.__setattr__(self, "parameter_fingerprint", expected)
        return self


class Run(Model):
    id: Key
    experiment_id: Key
    engine: str
    engine_version: str
    execution_commit: str | None = None
    job_sha256: Hash
    status: Literal["COMPLETE", "FAILED", "BLOCKED", "UNKNOWN"]
    kind: Literal["SYNTHETIC", "HISTORICAL", "PROSPECTIVE"]
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    evidence_reference: str
    evidence_sha256: Hash
    audit_status: Literal["SOURCE_AUDITED", "UNVERIFIED"]


class Case(Model):
    id: Key
    run_id: Key
    segment: str
    scenario: str
    period_start_utc: datetime
    period_end_utc: datetime
    warmup_bars: int = Field(ge=0)
    trades: int = Field(ge=0)
    net_return_pct: Number | None = None
    max_drawdown_pct: Nonnegative | None = None
    win_rate_pct: Annotated[float, Field(ge=0, le=100)] | None = None
    profit_factor: Nonnegative | None = None
    capital_initial: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    costs: dict[str, Nonnegative]
    metrics: dict[str, Number | None] = Field(default_factory=dict)
    audit_status: Literal["SOURCE_AUDITED", "UNVERIFIED"]

    @model_validator(mode="after")
    def period(self):
        if (
            self.period_start_utc.utcoffset() != UTC.utcoffset(None)
            or self.period_end_utc.utcoffset() != UTC.utcoffset(None)
            or self.period_start_utc >= self.period_end_utc
        ):
            raise ValueError("Require ordered UTC boundaries, end exclusive")
        return self


class Artifact(Model):
    id: Key
    run_id: Key
    artifact_type: str
    reference: str
    sha256: Hash
    verification_status: Literal["HASH_VERIFIED", "UNVERIFIED"]


class Decision(Model):
    id: Key
    strategy_id: Key
    version_id: Key | None = None
    run_id: Key | None = None
    category: Literal["RESEARCH", "ECONOMIC", "DEMO_ELIGIBILITY", "AUTHORIZATION"]
    verdict: str
    reasoning: str
    limitations: list[str]
    decided_by: str
    decided_at_utc: datetime | None

    @model_validator(mode="after")
    def utc(self):
        if self.decided_at_utc is not None and self.decided_at_utc.utcoffset() != UTC.utcoffset(
            None
        ):
            raise ValueError("Decision timestamp must be UTC")
        return self


class Bundle(Model):
    schema_version: Literal["1.0"] = "1.0"
    strategies: list[Strategy] = Field(default_factory=list)
    versions: list[Version] = Field(default_factory=list)
    experiments: list[Experiment] = Field(default_factory=list)
    runs: list[Run] = Field(default_factory=list)
    case_results: list[Case] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    research_decisions: list[Decision] = Field(default_factory=list)
