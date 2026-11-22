"""Bounded declarative gates and faithful mapping into the existing fingerprint.

This checks declared data, not future Python causality or economic significance.
Unknown expressions are refused, never evaluated or approved by keyword matching.
"""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator

from trading_lab_orchestration.contracts import HypothesisManifest, canonical

from .context import ResearchError
from .designer_models import SEMANTIC_VERSION, StrategySpecification, strict_json
from .models import ID, Contract, Text, Texts


class Expression(Contract):
    operator: Literal["PRICE", "SMA", "ROLLING_MAX", "ROLLING_MIN", "ATR_SMA"]
    input: Literal["open", "high", "low", "close", "OHLC"]
    window: int | ID
    shift: int = Field(ge=0, le=100000)
    centered: Literal[False]
    fill: Literal["NONE"]
    timeframe: Text
    closed: Literal[True]

    @field_validator("centered", "closed", mode="before")
    @classmethod
    def real_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("Boolean declarations cannot be numeric")
        return value


class Warmup(Contract):
    bars: int = Field(ge=1, le=100000)
    nan: Literal["BLOCK_ENTRY"]


class FeatureDefinition(Contract):
    formulas: list[ID] = Field(min_length=1, max_length=20)
    warmup: Warmup
    gaps: Literal["REJECT_DISCONTINUITIES"]


class Predicate(Contract):
    operator: Literal["GT", "LT", "GE", "LE"]
    left: ID
    right: ID


class Stop(Contract):
    type: Literal["ATR"]
    formula: ID
    multiple: float = Field(gt=0, le=100, allow_inf_nan=False)
    freeze: Literal["SIGNAL_CLOSE"]


class Target(Contract):
    type: Literal["RISK_REWARD"]
    multiple: float = Field(gt=0, le=100, allow_inf_nan=False)
    trailing: Literal[False]
    time_stop_bars: int | None = Field(ge=1, le=100000)

    @field_validator("trailing", mode="before")
    @classmethod
    def real_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("Boolean declaration required")
        return value


class Sizing(Contract):
    method: Literal["stop_risk", "fixed_notional"]
    capital_initial: float = Field(gt=0, allow_inf_nan=False)
    capital_policy: Literal["RESET_PER_SEGMENT", "CONTINUOUS"]
    risk_per_trade_pct: float = Field(gt=0, le=100, allow_inf_nan=False)
    max_position_pct: float = Field(gt=0, le=100, allow_inf_nan=False)
    max_exposure_pct: float = Field(gt=0, le=100, allow_inf_nan=False)
    max_open_positions: int = Field(ge=1, le=100)
    position_pct: float | None = Field(gt=0, le=100, allow_inf_nan=False)


class Evaluation(Contract):
    selection_segment: Literal["TRAIN"]
    holdout_independent: bool
    cost_application: Literal["BOTH_SIDES_FEE_ADVERSE_SLIPPAGE_HALF_SPREAD"]
    tests: Texts


def data(text: str, model: type[Contract]):
    return strict_json(text.encode(), model, 4000)


def _check(condition: bool, code: str):
    if not condition:
        raise ResearchError(code)


def seal_specification(
    spec: StrategySpecification, request, candidate, context, review, capabilities
):
    """Validate supplements first, then add semantic data inside fingerprint fields.

    The raw proposal remains in ReceiptBook. Pre-existing semantic envelopes are
    refused: the provider cannot forge a host freeze or normalize a historical one.
    """
    if spec.status != "SPECIFICATION_PREPARED":
        return spec, None
    m = spec.manifest
    raw = m.model_dump(mode="json")
    p, dataset = capabilities["protocol"], capabilities["dataset"]
    _check(
        spec.request_id == request.request_id
        and spec.research_hypothesis_id == candidate.hypothesis_id
        and m.hypothesis_id == candidate.hypothesis_id,
        "SPEC_IDENTITY_MISMATCH",
    )
    _check(m.market_hypothesis == candidate.statement, "HYPOTHESIS_CHANGED")
    _check(m.rationale == candidate.justification, "JUSTIFICATION_CHANGED")
    # Discovery multiplicity is host-validated input, not an optional model revision.
    # A larger declared total is a lower-bound-compatible declaration, not a new audit.
    searches = request.discovery.searches_count
    if searches is None:
        _check(m.novelty.known_searches is None, "DISCOVERY_MULTIPLICITY_UNVERIFIED")
    else:
        _check(
            m.novelty.known_searches is not None and m.novelty.known_searches >= searches,
            "DISCOVERY_MULTIPLICITY_LOST",
        )
    _check(spec.capability_reference_ids == [p["reference_id"]], "INVENTED_CAPABILITY")
    _check(SEMANTIC_VERSION not in canonical(raw), "UNTRUSTED_SEMANTIC_ENVELOPE")
    _check(m.execution_assumptions.runner_protocol == p["reference_id"], "RUNNER_UNSUPPORTED")
    market = request.market
    mode = m.execution_assumptions.market_mode
    _check(mode in p["market_modes"], "MARKET_UNSUPPORTED")
    _check(market.timeframe in p["timeframes"], "TIMEFRAME_UNSUPPORTED")
    _check(
        mode == market.market_type
        and m.data_requirements.assets == [market.asset]
        and m.data_requirements.timeframe == market.timeframe,
        "SPEC_MARKET_MISMATCH",
    )
    dm = dataset["market"]
    _check(
        (dm["asset"], dm["market_type"], dm["timeframe"])
        == (market.asset, market.market_type, market.timeframe),
        "DATASET_MARKET_MISMATCH",
    )
    _check(
        dataset["availability"] == "MANUALLY_VERIFIED"
        and m.data_requirements.availability == "MANUALLY_VERIFIED",
        "DATASET_PENDING",
    )
    _check(
        m.data_requirements.dataset_refs
        == [dataset["reference_id"] + ":sha256:" + dataset["sha256"]],
        "DATASET_IDENTITY_MISMATCH",
    )
    _check(m.data_requirements.funding_policy == p["funding"][mode], "FUNDING_UNSUPPORTED")
    _check(spec.capital_policy == p["capital_policy"], "CAPITAL_UNSUPPORTED")
    risk = spec.risk_constraints.model_dump()
    _check(risk["max_open_positions"] == p["max_open_positions"], "POSITIONS_UNSUPPORTED")
    supported = {d for d in ("LONG_ONLY", "SHORT_ONLY") if d not in m.signal_spec.unsupported_modes}
    _check(len(supported) == 1 and supported <= set(p["directions"][mode]), "DIRECTION_UNSUPPORTED")
    _check(m.data_requirements.gap_policy == p["gap_policy"], "GAP_POLICY_UNSUPPORTED")
    _check(m.execution_assumptions.intrabar_policy == p["intrabar"], "INTRABAR_UNSUPPORTED")
    _check(
        m.execution_assumptions.entry_timing == p["entry_timing"]
        and m.signal_spec.availability == p["signal_availability"],
        "CAUSALITY_UNSUPPORTED",
    )
    _check(all(limit in m.limitations for limit in candidate.limitations), "LIMITATION_DROPPED")
    # The host's original sources are identities, not model-supplied locators.
    _check(
        {s.reference for s in m.source_refs} == set(candidate.source_ids)
        and all(s.verification == "UNVERIFIED" for s in m.source_refs),
        "SOURCE_REFERENCE_MISMATCH",
    )
    features = data(m.signal_spec.feature_definitions, FeatureDefinition)
    _check(features.formulas == [f.name for f in spec.formulas], "FORMULA_CONTRADICTION")
    _check(features.warmup.bars == m.data_requirements.warmup_bars, "WARMUP_CONTRADICTION")
    params = m.parameter_space.parameters
    _check(all(len(p.values) == 1 for p in params.values()), "PARAMETERS_NOT_FROZEN")
    used_params, expressions = set(), {}
    for f in spec.formulas:
        e = data(f.expression, Expression)
        window = e.window
        if isinstance(window, str):
            _check(window in params, "PARAMETER_REFERENCE_MISSING")
            used_params.add(window)
            window = params[window].values[0]
        _check(type(window) is int and 1 <= window <= 100000, "WINDOW_INVALID")
        _check(f.lookback_bars == window and f.shift_bars == e.shift, "FORMULA_CONTRADICTION")
        _check(e.timeframe == market.timeframe and e.closed, "TIMEFRAME_UNSUPPORTED")
        _check(f.availability == "CANDLE_CLOSE" and f.units == "PRICE", "FORMULA_UNITS_UNSUPPORTED")
        _check(
            f.gap_rule == features.gaps and data(f.warmup_rule, Warmup) == features.warmup,
            "FORMULA_POLICY_CONTRADICTION",
        )
        _check(
            features.warmup.bars >= window + e.shift + int(e.operator == "ATR_SMA"),
            "WARMUP_INSUFFICIENT",
        )
        _check((e.operator == "ATR_SMA") == (e.input == "OHLC"), "INDICATOR_INPUT_UNSUPPORTED")
        _check(e.operator != "PRICE" or window == 1, "PRICE_WINDOW_INVALID")
        expressions[f.name] = e.model_dump(mode="json")
    _check(set(params) == used_params, "UNMAPPED_PARAMETER")
    known = set(expressions) | {"open", "high", "low", "close"}
    _check(not set(expressions) & {"open", "high", "low", "close"}, "RESERVED_FORMULA_NAME")
    for rule in (
        m.signal_spec.long_entry,
        m.signal_spec.long_exit,
        m.signal_spec.short_entry,
        m.signal_spec.short_exit,
    ):
        if rule is not None:
            predicate = data(rule, Predicate)
            _check(
                predicate.left in known and predicate.right in known, "SIGNAL_DEPENDENCY_UNKNOWN"
            )
    stop, sizing = (
        data(m.execution_assumptions.stop, Stop),
        data(m.execution_assumptions.sizing, Sizing),
    )
    data(m.execution_assumptions.target, Target)
    _check(
        stop.formula in expressions
        and expressions[stop.formula]["operator"] == "ATR_SMA"
        and expressions[stop.formula]["shift"] == 0,
        "STOP_DEPENDENCY_INVALID",
    )
    _check(
        sizing.method in p["sizing_methods"] and sizing.capital_policy == spec.capital_policy,
        "SIZING_UNSUPPORTED",
    )
    _check(all(getattr(sizing, k) == v for k, v in risk.items()), "RISK_CONTRADICTION")
    _check(
        (sizing.method == "fixed_notional") == (sizing.position_pct is not None),
        "POSITION_SIZE_MISSING",
    )
    _check(
        sizing.position_pct is None or sizing.position_pct <= sizing.max_position_pct,
        "POSITION_SIZE_INVALID",
    )
    scenarios = {c.name: c.model_dump() for c in spec.cost_scenarios}
    _check(set(scenarios) == {"BASE", "ADVERSE"}, "COST_SCENARIOS_MISSING")
    for field in ("trading_fee_pct", "slippage_pct", "spread_pct"):
        _check(
            getattr(m.execution_assumptions, field) == scenarios["BASE"][field],
            "BASE_COST_CONTRADICTION",
        )
        _check(scenarios["ADVERSE"][field] >= scenarios["BASE"][field], "ADVERSE_COST_REDUCED")
    for scenario in scenarios.values():
        _check(
            scenario["trading_fee_pct"] < 100
            and scenario["slippage_pct"] + scenario["spread_pct"] / 2 < 100,
            "EXECUTION_COST_LIMIT",
        )
    evaluation = data(m.evaluation_plan.robustness_plan, Evaluation)
    _check(
        m.evaluation_plan.walk_forward == "DISABLED_TRAIN_ONLY_SELECTION", "SELECTION_UNSUPPORTED"
    )
    _check(evaluation.cost_application == p["cost_application"], "COST_APPLICATION_UNSUPPORTED")
    _check(m.evaluation_plan.falsification in candidate.falsification, "FALSIFICATION_CHANGED")
    _check(m.evaluation_plan.holdout_status != "UNKNOWN", "HOLDOUT_UNKNOWN")
    start = datetime.fromisoformat(dm["coverage_start_utc"])
    end = datetime.fromisoformat(dm["coverage_end_utc"])
    seconds = (
        int(market.timeframe[:-1])
        * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[market.timeframe[-1]]
    )
    _check(
        start <= m.evaluation_plan.train.start - timedelta(seconds=seconds * features.warmup.bars)
        and m.evaluation_plan.test.end <= end,
        "DATASET_COVERAGE_INSUFFICIENT",
    )
    discovery = request.discovery
    discovery_overlap = (
        discovery.period_start_utc is not None
        and datetime.fromisoformat(discovery.period_start_utc) < m.evaluation_plan.test.end
        and datetime.fromisoformat(discovery.period_end_utc) > m.evaluation_plan.test.start
    )
    applicable_consumed = any(
        e["holdout"] == "CONSUMED" and e.get("dataset_sha256") == dataset["sha256"]
        for e in context["experiments"]
    )
    if discovery_overlap or applicable_consumed:
        _check(m.evaluation_plan.holdout_status == "CONSUMED", "HOLDOUT_RECLASSIFIED")
    _check(
        not evaluation.holdout_independent
        or m.evaluation_plan.holdout_status == "UNOBSERVED_DECLARED",
        "FALSE_INDEPENDENT_HOLDOUT",
    )
    if spec.implementation_operation == "NEW_EXPERIMENT":
        # Reuse requires a host-reviewed exact signal template, never a name match.
        reuse = review.get("reuse")
        _check(reuse is not None and not m.requires_new_strategy_code, "REUSE_NOT_VERIFIED")
        version = next((v for v in context["versions"] if v["id"] == reuse["version_id"]), None)
        _check(
            version is not None
            and version["code_sha256"] == reuse["code_sha256"]
            and version["configuration_sha256"] == reuse["configuration_sha256"],
            "REUSE_IDENTITY_MISMATCH",
        )
        _check(reuse["signal_template"] == signal_template(spec), "REUSE_SIGNAL_MISMATCH")
        schema = version["parameter_schema"]
        _check(
            set(schema) == {"type", "properties", "required", "additionalProperties"}
            and schema["type"] == "object"
            and schema["additionalProperties"] is False
            and set(schema["properties"]) == set(params) == set(schema["required"]),
            "REUSE_PARAMETER_SCHEMA_UNSUPPORTED",
        )
        for name, parameter in params.items():
            definition, value = schema["properties"][name], parameter.values[0]
            _check(
                set(definition) == {"type", "minimum", "maximum"}
                and definition["type"] == "integer"
                and type(value) is int
                and type(definition["minimum"]) is int
                and type(definition["maximum"]) is int
                and definition["minimum"] <= value <= definition["maximum"],
                "REUSE_PARAMETER_OUT_OF_RANGE",
            )
    else:
        _check(m.requires_new_strategy_code, "IMPLEMENTATION_OPERATION_CONTRADICTION")

    # All complementary scientific objects enter fields covered by fingerprint().
    def envelope(declared, payload):
        return canonical(
            {"semantic_version": SEMANTIC_VERSION, "declared": declared, "scientific_data": payload}
        )

    raw["signal_spec"]["feature_definitions"] = envelope(
        raw["signal_spec"]["feature_definitions"],
        {"formulas": [f.model_dump(mode="json") for f in spec.formulas]},
    )
    raw["execution_assumptions"]["sizing"] = envelope(
        raw["execution_assumptions"]["sizing"],
        {"capital_policy": spec.capital_policy, "risk_constraints": risk},
    )
    raw["evaluation_plan"]["robustness_plan"] = envelope(
        raw["evaluation_plan"]["robustness_plan"],
        {
            "cost_scenarios": [scenarios[k] for k in sorted(scenarios)],
            "capability_fingerprint": review["capability_fingerprint"],
            "protocol_sha256": capabilities["protocol_sha256"],
            "dataset_sha256": dataset["sha256"],
        },
    )
    mapped = HypothesisManifest.model_validate_json(canonical(raw))
    result = spec.model_dump(mode="json")
    result["manifest"] = mapped.model_dump(mode="json")
    sealed = strict_json(canonical(result).encode(), StrategySpecification)
    return sealed, {
        "semantic_version": SEMANTIC_VERSION,
        "original_manifest_fingerprint": m.fingerprint(),
        "manifest_fingerprint": mapped.fingerprint(),
        "parameters_frozen": True,
        "protocol_frozen": True,
    }


def signal_template(spec: StrategySpecification) -> dict:
    """Host reuse witness. Parameters remain symbolic; implementation is not inferred."""
    m = spec.manifest
    return {
        "formulas": [
            {
                k: v
                for k, v in f.model_dump(mode="json").items()
                if k not in {"lookback_bars", "warmup_rule"}
            }
            for f in spec.formulas
        ],
        "signals": {
            k: v
            for k, v in m.signal_spec.model_dump(mode="json").items()
            if k != "feature_definitions"
        },
        "parameter_names": sorted(m.parameter_space.parameters),
        "stop": m.execution_assumptions.stop,
        "target": m.execution_assumptions.target,
    }
