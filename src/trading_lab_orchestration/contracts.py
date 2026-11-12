"""Manual strategy card and HypothesisManifest are the same versioned contract.

Free text is descriptive data, never a command, permission or scientific certification.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
Percentage = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Scalar = str | bool | int | Annotated[float, Field(allow_inf_nan=False)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, frozen=True)


class SourceRef(Model):
    reference: Text
    accessed_on: date
    verification: Literal["MANUAL", "UNVERIFIED"]


class DataRequirements(Model):
    assets: list[Text] = Field(min_length=1)
    timeframe: Annotated[str, Field(pattern=r"^[1-9][0-9]*[mhdw]$")]
    horizon: Text
    warmup_bars: int = Field(ge=0)
    gap_policy: Text
    funding_policy: Literal["NOT_APPLICABLE", "NOT_MODELLED", "REQUIRED"]
    dataset_refs: list[Text] = Field(min_length=1)
    availability: Literal["UNVERIFIED", "PENDING", "MANUALLY_VERIFIED"]


class SignalSpec(Model):
    long_entry: Text | None
    long_exit: Text | None
    short_entry: Text | None
    short_exit: Text | None
    unsupported_modes: list[Literal["LONG_ONLY", "SHORT_ONLY"]]
    availability: Literal["CANDLE_CLOSE"]
    feature_definitions: Text

    @model_validator(mode="after")
    def modes(self) -> Self:
        supported = 0
        for mode, entry, exit_ in (
            ("LONG_ONLY", self.long_entry, self.long_exit),
            ("SHORT_ONLY", self.short_entry, self.short_exit),
        ):
            if mode in self.unsupported_modes:
                if entry is not None or exit_ is not None:
                    raise ValueError(f"{mode}: unsupported requires null entry and exit")
            elif entry is None or exit_ is None:
                raise ValueError(f"{mode}: entry and exit are required")
            else:
                supported += 1
        if not supported:
            raise ValueError("At least one direction must be specified")
        return self


class Parameter(Model):
    values: list[Scalar] = Field(min_length=1)
    rationale: Text

    @field_validator("values")
    @classmethod
    def distinct(cls, values: list[Scalar]) -> list[Scalar]:
        encoded = [canonical(value) for value in values]
        if len(encoded) != len(set(encoded)):
            raise ValueError("Duplicate parameter values")
        return values


class ParameterSpace(Model):
    parameters: dict[Identifier, Parameter]
    combination_limit: int = Field(ge=1, le=100000)
    limit_rationale: Text

    @model_validator(mode="after")
    def bounded(self) -> Self:
        combinations = 1
        for parameter in self.parameters.values():
            combinations *= len(parameter.values)
        if combinations > self.combination_limit:
            raise ValueError("Parameter space exceeds declared combination_limit")
        return self


class ExecutionAssumptions(Model):
    market_mode: Literal["spot", "synthetic", "perpetual"]
    runner_protocol: Text
    entry_timing: Literal["NEXT_OPEN"]
    trading_fee_pct: Percentage
    slippage_pct: Percentage
    spread_pct: Percentage
    stop: Text
    target: Text
    sizing: Text
    intrabar_policy: Text


class Period(Model):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("Timestamp must explicitly use UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("Period start must precede exclusive end")
        return self


class EvaluationPlan(Model):
    train: Period
    validation: Period
    test: Period
    holdout_status: Literal["UNOBSERVED_DECLARED", "CONSUMED", "UNKNOWN"]
    holdout_risk: Text
    walk_forward: Text
    primary_metric: Text
    falsification: Text
    robustness_plan: Text

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.train.end > self.validation.start or self.validation.end > self.test.start:
            raise ValueError("TRAIN/VALIDATION/TEST must be chronological and disjoint")
        return self


class Novelty(Model):
    prior_work: Text
    known_searches: int | None = Field(ge=0)
    known_variants: int | None = Field(ge=0)


class HypothesisManifest(Model):
    schema_version: Literal["1.0"]
    hypothesis_id: Identifier
    created_at_utc: datetime
    researcher_version: Text
    title: Text
    market_hypothesis: Text
    rationale: Text
    source_refs: list[SourceRef] = Field(min_length=1)
    data_requirements: DataRequirements
    signal_spec: SignalSpec
    parameter_space: ParameterSpace
    execution_assumptions: ExecutionAssumptions
    evaluation_plan: EvaluationPlan
    novelty: Novelty
    limitations: list[Text] = Field(min_length=1)
    expected_compute_class: Literal["SMALL", "MEDIUM", "LARGE", "UNKNOWN"]
    requires_new_strategy_code: bool
    status: Literal["PROPOSED"]

    _utc = field_validator("created_at_utc")(Period.utc.__func__)

    @model_validator(mode="after")
    def compatible(self) -> Self:
        mode = self.execution_assumptions.market_mode
        funding = self.data_requirements.funding_policy
        if mode == "spot" and "SHORT_ONLY" not in self.signal_spec.unsupported_modes:
            raise ValueError("Spot requires unsupported SHORT_ONLY")
        if mode == "spot" and funding != "NOT_APPLICABLE":
            raise ValueError("Spot funding must be NOT_APPLICABLE")
        if mode == "synthetic" and funding != "NOT_MODELLED":
            raise ValueError("Synthetic funding must be NOT_MODELLED")
        if mode == "perpetual" and funding != "REQUIRED":
            raise ValueError("Perpetual funding must be REQUIRED; runner review remains pending")
        return self

    def snapshot(self) -> str:
        return canonical(self.model_dump(mode="json"))

    def fingerprint(self) -> str:
        """Exact scientific specification; metadata/title changes do not create work."""
        payload = self.model_dump(mode="json")
        fields = (
            "schema_version",
            "market_hypothesis",
            "data_requirements",
            "signal_spec",
            "parameter_space",
            "execution_assumptions",
            "evaluation_plan",
        )
        return digest(canonical({key: payload[key] for key in fields}))


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_manifest(path: Path) -> HypothesisManifest:
    payload = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique)
    # JSON-mode strict validation allows ISO dates, without coercing strings into numbers/bools.
    return HypothesisManifest.model_validate_json(canonical(payload))
