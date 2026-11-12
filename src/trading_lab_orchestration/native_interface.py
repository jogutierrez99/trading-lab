"""Shared cheap signal-interface probe; no fills, datasets, model calls or economic gate."""

from pathlib import Path


def check_signal_interface(registry, template, parameters, market, frame, period):
    from quant_lab.config import MarketConfig
    from quant_lab.lab_runner import parameter_risk, window

    cls = registry.implementation(template.name)
    config = template.model_copy(
        update={
            "market": MarketConfig(
                symbol=market.symbol.replace("USDT", "/USDT"), timeframe=market.timeframe
            ),
            "parameters": parameters,
            "risk": parameter_risk(cls, template.risk, parameters),
        }
    )
    strategy = registry.create(config)
    view, _ = window(frame, market, period)
    prefix = view.iloc[: market.warmup_bars + 2].copy(deep=True)
    original = prefix.copy(deep=True)
    try:
        import pandas as pd

        features = strategy.prepare_features(prefix.copy(deep=True))
        if not features.index.equals(prefix.index):
            raise ValueError("Features must preserve the native timestamp index")
        strategy.generate_signals(prefix)
        pd.testing.assert_frame_equal(prefix, original)
    except (AttributeError, ValueError, TypeError, KeyError, AssertionError) as exc:
        raise ValueError(
            f"Strategy incompatible with native indexed OHLCV interface: {exc}"
        ) from exc


def implementation_interface(request):
    import sys
    from datetime import UTC, datetime, timedelta

    import pandas as pd

    workspace = Path(request.workspace).resolve()
    sys.path.insert(0, str(workspace / "src"))
    import quant_lab
    from quant_lab.config import AppConfig, RiskConfig, StrategyConfig, _read_mapping, load_yaml
    from quant_lab.lab_schema import Experiment, Market, Period
    from quant_lab.strategies.registry import StrategyRegistry
    from quant_lab.study_backend import candle_step

    if not Path(quant_lab.__file__).resolve().is_relative_to(workspace):
        raise ValueError("Native interface import escaped the implementation workspace")
    if request.plan.operation == "NEW_STRATEGY":
        profile = workspace / request.plan.paths()[1]
        app_path = workspace / "configs/app.yaml"
        timeframe = request.hypothesis_manifest.data_requirements.timeframe
        symbol = request.hypothesis_manifest.data_requirements.assets[0].replace("/", "")
        overrides = {}
        expected_strategy = request.plan.target
    else:
        path = workspace / request.plan.paths()[0]
        experiment = load_yaml(path, Experiment)
        profile = (path.parent / experiment.strategy.config).resolve()
        app_path = (path.parent / experiment.app).resolve()
        timeframe, symbol = experiment.markets[0].timeframe, experiment.markets[0].symbol
        overrides = next(experiment.grid())  # One representative configuration, not a sweep.
        expected_strategy = experiment.strategy.id
    if any(not p.resolve().is_relative_to(workspace) for p in (profile, app_path)):
        raise ValueError("Native probe config escaped the implementation workspace")
    app = load_yaml(app_path, AppConfig)
    risk_path = (app_path.parent / app.risk_file).resolve()
    if not risk_path.is_relative_to(workspace):
        raise ValueError("Native probe risk escaped the implementation workspace")
    risk = load_yaml(risk_path, RiskConfig)
    raw = _read_mapping(profile)
    from .circuit_contracts import technical_profile

    technical = technical_profile(request.hypothesis_manifest) is not None
    if technical and (
        raw.get("enabled") is not False or raw.get("parameters", {}) != {} or raw.get("risk")
    ):
        raise ValueError(
            "Technical circuit requires disabled YAML, empty parameters and no risk overrides"
        )
    raw["enabled"] = True  # In-memory only: never enable the delivered/operational YAML.
    raw["risk"] = risk.model_dump() | raw.get("risk", {})
    template = StrategyConfig.model_validate(raw)
    if template.name != expected_strategy:
        raise ValueError("Native probe profile contradicts the implementation strategy")
    registry = StrategyRegistry().discover()
    cls = registry.implementation(template.name)
    if technical and (
        cls.version != "1.0.0"
        or cls.parameter_model.model_fields
        or cls.lab_modes != ("LONG_ONLY",)
        or cls.lab_timeframes != ("1h",)
        or cls.required_warmup({}, "1h") != 20
        or cls.lab_price_levels
    ):
        raise ValueError("Technical circuit metadata/parameters/warmup contradict the frozen card")
    if cls.lab_execution != "ohlcv" or timeframe not in cls.lab_timeframes:
        raise ValueError("Native probe requires a supported ordinary OHLCV timeframe")
    parameters = cls.parameter_model.model_validate(template.parameters | overrides).model_dump()
    warmup = max(
        request.hypothesis_manifest.data_requirements.warmup_bars,
        cls.required_warmup(parameters, timeframe),
    )
    if warmup > 1000:
        raise ValueError("Native probe warmup exceeds cheap-check limit1000; review separately")
    step = candle_step(timeframe)
    start = datetime(2000, 1, 10, tzinfo=UTC)
    period = Period(start=start, end=start + timedelta(seconds=step.total_seconds() * 2))
    index = pd.date_range(
        pd.Timestamp(start) - warmup * step, periods=warmup + 2, freq=step, name="open_time"
    )
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=index
    )
    market = Market(
        symbol=symbol,
        timeframe=timeframe,
        dataset="NOT_READ_SYNTHETIC_IN_MEMORY",
        warmup_bars=warmup,
    )
    check_signal_interface(registry, template, parameters, market, frame, period)
    report = {
        "status": "VALID",
        "scope": "SYNTHETIC_NATIVE_INTERFACE_ONLY",
        "strategy": template.name,
        "version": template.version,
        "timeframe": timeframe,
        "rows": len(frame),
        "warmup_bars": warmup,
        "timezone": "UTC",
        "timestamp_column": False,
        "profile_file_modified": False,
        "historical_data_read": False,
        "backtests_executed": 0,
        "economic_assessment": "NOT_ASSESSED",
    }
    if technical:
        from .circuit_fixture import check_pulse_signal_contract

        report["technical_contract"] = check_pulse_signal_contract(registry.create(template))
    return report
