"""Designer 1.0 contracts. JSON data is never a program or an authorization."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import HypothesisManifest

from .models import ID, Contract, IDs, Text, Texts

DESIGNER_VERSION = "TLAgents.designer/1.0"
SEMANTIC_VERSION = "TLAgents.semantic/1.0"
SPEC_LIMIT = 64 * 1024

Percentage = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]


class Formula(Contract):
    name: Text
    expression: Text
    units: Text
    availability: Text
    lookback_bars: int = Field(ge=0, le=100000)
    shift_bars: int = Field(ge=0, le=100000)
    warmup_rule: Text
    gap_rule: Text


class RiskConstraints(Contract):
    risk_per_trade_pct: Positive
    max_position_pct: Positive
    max_exposure_pct: Positive
    max_open_positions: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def exposure(self) -> Self:
        if self.max_position_pct > self.max_exposure_pct:
            raise ValueError("Position cannot exceed exposure")
        return self


class CostScenario(Contract):
    name: Literal["BASE", "ADVERSE"]
    trading_fee_pct: Percentage
    slippage_pct: Percentage
    spread_pct: Percentage


class StrategySpecification(Contract):
    schema_version: Literal["1.0"]
    contract_kind: Literal["StrategySpecification"]
    request_id: ID
    research_hypothesis_id: ID
    status: Literal["DRAFT", "NEEDS_REVIEW", "SPECIFICATION_PREPARED"]
    manifest: HypothesisManifest | None
    capital_policy: Literal["RESET_PER_SEGMENT", "CONTINUOUS", "UNKNOWN"]
    formulas: Annotated[list[Formula], Field(max_length=20)]
    risk_constraints: RiskConstraints | None
    cost_scenarios: Annotated[list[CostScenario], Field(max_length=2)]
    capability_reference_ids: IDs
    implementation_operation: Literal["NEW_STRATEGY", "NEW_EXPERIMENT", "UNSUPPORTED"]
    missing_fields: Texts
    review_requirements: Texts
    notes: Text | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        for values in (
            [f.name for f in self.formulas],
            [c.name for c in self.cost_scenarios],
            self.capability_reference_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate scientific identity")
        if self.status == "SPECIFICATION_PREPARED" and (
            self.manifest is None
            or self.risk_constraints is None
            or not self.formulas
            or not self.cost_scenarios
            or not self.capability_reference_ids
            or self.missing_fields
            or self.review_requirements
            or self.capital_policy == "UNKNOWN"
            or self.implementation_operation == "UNSUPPORTED"
        ):
            raise ValueError("Prepared specification is incomplete")
        if self.status == "NEEDS_REVIEW" and not (self.missing_fields or self.review_requirements):
            raise ValueError("Review needs an explicit diagnostic")
        return self


def strict_json(raw: bytes, model: type[Contract], limit: int = SPEC_LIMIT):
    """Duplicate/finite/depth checks followed by Pydantic's strict JSON semantics.

    ISO dates inside the unchanged HypothesisManifest must be parsed in JSON mode;
    strict Python validation would incorrectly reject their string representation.
    """
    if type(raw) is not bytes or not raw or len(raw) > limit:
        raise ValueError("Invalid bounded JSON input")
    try:
        value = parse(raw.decode("utf-8"))
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 24:
                raise ValueError("Excessive JSON nesting")
            if isinstance(item, dict):
                pending.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth + 1) for v in item)
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return model.model_validate_json(raw)
    except (RecursionError, OverflowError):
        raise ValueError("JSON exceeds parser limits") from None
