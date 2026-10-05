"""Local orchestration; execution, risk, metrics and persistence remain existing layers."""

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from difflib import get_close_matches
from pathlib import Path

import pandas as pd

from quant_lab.config import (
    AppConfig,
    MarketConfig,
    RiskConfig,
    StrategyConfig,
    _read_mapping,
    load_yaml,
)
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.features import atr
from quant_lab.indicators import volatility_fractions
from quant_lab.lab_data import check_periods, inspect_bundle, load_bundle
from quant_lab.lab_schema import Experiment, experiment_periods
from quant_lab.metrics import summarize
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.study_backend import Segment, StudyBackend, candle_step, validate_segment
from quant_lab.study_data import HOURS

DIRECTIONS = {"LONG_ONLY": "long", "SHORT_ONLY": "short", "LONG_SHORT": "combined"}


def parameter_risk(cls, risk, parameters):
    """Explicit strategy opt-in; never changes global defaults or sizing semantics."""
    return RiskConfig.model_validate(
        risk.model_dump()
        | {field: parameters[param] for param, field in cls.lab_risk_parameters.items()}
    )


def prepare(path: Path, experiment: Experiment, full: bool = False) -> dict:
    base = path.parent
    registry = StrategyRegistry().discover()
    cls = registry.implementation(experiment.strategy.id)
    if cls.lab_execution not in {"ohlcv", "perpetual_funding"}:
        raise ValueError(f"Strategy requires {cls.lab_execution}; use its dedicated legacy runner")
    perpetual = cls.lab_execution == "perpetual_funding"
    if perpetual != (experiment.execution.market_mode == "perpetual"):
        raise ValueError("Perpetual funding requires its explicit perpetual execution profile")
    app_path = (base / experiment.app).resolve()
    app = load_yaml(app_path, AppConfig)
    global_risk = load_yaml(app_path.parent / app.risk_file, RiskConfig)
    raw = _read_mapping(base / experiment.strategy.config)
    raw["risk"] = global_risk.model_dump() | raw.get("risk", {})
    template = StrategyConfig.model_validate(raw)
    if template.name != experiment.strategy.id:
        raise ValueError("Strategy config name does not match experiment strategy.id")
    if template.market.provider != "binance":
        raise ValueError("Ordinary lab adapter currently supports Binance OHLCV datasets only")
    registry.create(template)  # Enabled flag, version and parameter model.
    risk = template.risk
    if cls.lab_price_levels:
        if (
            risk.stop_method != "structure"
            or not risk.stop_enabled
            or not risk.take_profit_enabled
            or risk.trailing_atr_multiplier is not None
        ):
            raise ValueError("Absolute-level strategy requires structural stop/target, no trailing")
    elif risk.stop_enabled and risk.stop_method != "atr":
        raise ValueError("Ordinary lab adapter supports ATR stops; use specialized runner")
    keys = cls.parameter_model.model_fields
    for name in experiment.strategy_parameters:
        if name not in keys:
            suggestion = get_close_matches(name, keys, n=1)
            raise ValueError(
                f"Unknown parameter {name!r}; did you mean {suggestion or list(keys)}?"
            )
    configs = []
    seen = set()
    for params in experiment.grid():
        resolved = cls.parameter_model.model_validate(template.parameters | params).model_dump()
        key = json.dumps(resolved, sort_keys=True)
        if key in seen:
            raise ValueError("Duplicate resolved parameter combinations")
        seen.add(key)
        parameter_risk(cls, risk, resolved)
        configs.append(resolved)
    for mode in experiment.modes:
        if mode not in cls.lab_modes:
            raise ValueError(f"Strategy does not support {mode}; supported: {cls.lab_modes}")
    datasets, frames = [], []
    auxiliary = {}
    common_days = None
    for market in experiment.markets:
        if market.timeframe not in cls.lab_timeframes:
            raise ValueError(f"Strategy requires timeframes {cls.lab_timeframes}")
        minimum = max(cls.required_warmup(p, market.timeframe) for p in configs)
        if market.warmup_bars < minimum:
            raise ValueError(f"Strategy requires at least {minimum} warmup bars")
        if (
            market.dataset_format == "mtf_quarters"
            and experiment.execution.market_mode != "synthetic"
        ):
            raise ValueError(
                "USD-M quarter prices require explicit synthetic execution; no funding"
            )
        if (
            risk.sizing_method == "volatility_target"
            and market.timeframe not in cls.lab_volatility_timeframes
        ):
            raise ValueError("Volatility sizing is hourly; use cross-market runner for translation")
        info = inspect_bundle(base, market)
        check_periods(info, market, experiment)
        if perpetual:
            from quant_lab.literature_data import complete_days, inspect_aux, load_aux

            if (
                market.timeframe != "1h"
                or risk.sizing_method != "stop_risk"
                or risk.trailing_atr_multiplier is not None
            ):
                raise ValueError("Funding adapter supports 1h stop-risk, no trailing")
            aux_info = inspect_aux(base, market)
            info["perpetual"] = aux_info
            metadata = aux_info["manifest"]
            for label, period in experiment_periods(experiment):
                left = pd.Timestamp(period.start) - market.warmup_bars * pd.Timedelta(hours=1)
                if pd.Timestamp(metadata["funding_start"]) > left or pd.Timestamp(
                    metadata["funding_end"]
                ).floor("h") + pd.Timedelta(hours=8) < pd.Timestamp(period.end):
                    raise ValueError(f"{label}: BLOCKED_BY_DATA, observed funding coverage")
            if full:
                aux = load_aux(aux_info)
                auxiliary[market.symbol] = aux
                days = complete_days(aux)
                common_days = days if common_days is None else common_days.intersection(days)
        elif market.perpetual_data is not None:
            raise ValueError("Perpetual auxiliary data requires the explicit funding adapter")
        datasets.append(info)
        if full:
            frame = load_bundle(info)
            for label, period in experiment_periods(experiment):
                view, segment = window(frame, market, period)
                validate_segment(view, segment)
                if len(view) != market.warmup_bars + int(
                    (segment.end - segment.start) / candle_step(market.timeframe)
                ):
                    raise ValueError(f"Incomplete warmup for {label}")
            frames.append(frame)
    if experiment.initial_cash is not None:
        app = app.model_copy(update={"starting_capital": experiment.initial_cash})
    if experiment.costs is not None:
        app = app.model_copy(update={"costs": experiment.costs})
    scenarios = {"base": app.costs} | experiment.validation.cost_stress
    for name, costs in experiment.validation.cost_stress.items():
        if any(getattr(costs, k) < v for k, v in app.costs.model_dump().items()):
            raise ValueError(f"Stress {name} must not lower any base cost")
    count = len(configs) * len(datasets) * len(experiment.modes) * len(scenarios)
    count *= (
        3
        + len(getattr(experiment, "diagnostic_periods", {}))
        + len(experiment.validation.walk_forward)
    )
    count += (
        len(datasets)
        * len(experiment.modes)
        * len(scenarios)
        * len(experiment.validation.walk_forward)
    )
    if perpetual and full:
        for label, period in experiment_periods(experiment):
            if not (
                (common_days >= pd.Timestamp(period.start))
                & (common_days < pd.Timestamp(period.end))
            ).any():
                raise ValueError(f"{label}: BLOCKED_BY_DATA, no funding/mark-complete common days")
    return dict(
        registry=registry,
        app=app,
        template=template,
        parameters=configs,
        datasets=datasets,
        frames=frames,
        scenarios=scenarios,
        backtests=count,
        auxiliary=auxiliary,
        funding_days=common_days,
    )


def window(frame, market, period):
    step = candle_step(market.timeframe)
    start, end = pd.Timestamp(period.start), pd.Timestamp(period.end)
    view = frame.loc[(frame.index >= start - market.warmup_bars * step) & (frame.index < end)]
    return view, Segment(market.symbol, market.timeframe, start, end)


def evaluate(context, frame, market, mode, parameters, period, costs):
    config = context["template"].model_copy(
        update={
            "market": MarketConfig(
                symbol=market.symbol.replace("USDT", "/USDT"), timeframe=market.timeframe
            ),
            "parameters": parameters,
            "risk": parameter_risk(
                context["registry"].implementation(context["template"].name),
                context["template"].risk,
                parameters,
            ),
        }
    )
    strategy = context["registry"].create(config)
    candles, segment = window(frame, market, period)
    if strategy.lab_execution == "perpetual_funding":
        from quant_lab.lab_funding_adapter import execute

        execution = context["execution"].model_copy(update={"direction": DIRECTIONS[mode]})
        return execute(
            candles,
            strategy,
            segment,
            context["app"].model_copy(update={"costs": costs}),
            config.risk,
            execution,
            context["auxiliary"][market.symbol],
            context["funding_days"],
        )
    signals = strategy.generate_signals(candles.copy(deep=True))
    distances = atr(candles, config.risk.atr_period) * config.risk.atr_multiplier
    fractions = None
    if config.risk.sizing_method == "volatility_target":
        r = config.risk
        fractions = volatility_fractions(
            candles.close,
            r.volatility_period,
            r.target_volatility_pct,
            r.min_position_pct,
            min(r.max_position_pct, r.max_exposure_pct),
            annual_bars=365 * 24 / HOURS[market.timeframe],
        )
    execution = ExecutionConfig.model_validate(
        context["execution"].model_dump() | {"direction": DIRECTIONS[mode]}
    )
    options = {"entry_levels": strategy.entry_levels(candles)} if strategy.lab_price_levels else {}
    result = StudyBackend().run(
        candles,
        signals,
        distances,
        segment,
        context["app"].model_copy(update={"costs": costs}),
        config.risk,
        execution,
        fractions,
        **options,
    )
    if strategy.lab_extended_metrics:
        from quant_lab.intraday_metrics import diagnostic_result

        result = diagnostic_result(
            result,
            candles,
            signals,
            segment,
            strategy.name,
            hours_per_bar=candle_step(market.timeframe).total_seconds() / 3600,
        )
        if strategy.lab_entry_diagnostics:
            from quant_lab.literature_metrics import enrich

            result = enrich(result, strategy, candles, fractions)
    return result


def rank_key(row: dict, experiment: Experiment):
    value = row.get(experiment.ranking.metric)
    return (
        value is None,
        0 if value is None else -value if experiment.ranking.descending else value,
        row["configuration_id"],
    )


def run(
    path: Path,
    experiment: Experiment,
    root: Path,
    output: Path | None = None,
    *,
    resume: str | None = None,
    check_only: bool = False,
) -> Path | dict:
    from quant_lab.lab_reporting import reports

    context = prepare(path, experiment, full=True)  # All data verified before creating a run.
    context["execution"] = experiment.execution
    code = provenance(root)
    plan = experiment.model_dump(mode="json")
    resolved = {
        "app": context["app"].model_dump(mode="json"),
        "strategy": context["template"].model_dump(mode="json"),
        "parameters": context["parameters"],
        "parameter_risks": [
            parameter_risk(
                context["registry"].implementation(context["template"].name),
                context["template"].risk,
                p,
            ).model_dump(mode="json")
            for p in context["parameters"]
        ]
        if context["registry"].implementation(context["template"].name).lab_risk_parameters
        else None,
        "datasets": context["datasets"],
        "backend": "perpetual_funding_v1"
        if context["registry"].implementation(context["template"].name).lab_execution
        == "perpetual_funding"
        else "study_backend_v1",
        "execution": experiment.execution.model_dump(),
    }
    recovery = None
    destination = (output or root / "results") / experiment.experiment_id
    if check_only and resume is None:
        raise ValueError("--check requires --resume")
    if resume is not None:
        from quant_lab.lab_resume import Recovery, select_source

        recovery = Recovery(select_source(destination, resume), plan, resolved, code)
        if check_only:
            return recovery.summary()
        if recovery.already_complete():
            print("Run already complete and verified; no backtests executed", file=sys.stderr)
            return recovery.source
    store = ExperimentStore(destination, plan, code)
    with (store.path / "experiment_snapshot.yaml").open("x", encoding="utf-8") as handle:
        handle.write(path.read_text(encoding="utf-8"))
    write_json(store.path / "resolved.json", resolved)
    write_json(store.path / "environment.json", code)
    write_json(
        store.path / "run.json",
        {
            "kind": "lab_experiment_v1",
            "experiment_id": experiment.experiment_id,
            "run_id": store.run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "expected_backtests": context["backtests"],
        },
    )
    print(f"Run {store.run_id}: {context['backtests']} backtests; {store.path}", file=sys.stderr)
    rows = []
    if recovery:
        recovery.attach(store)

    def one(frame, market, mode, params, label, period, scenario, costs):
        identity = {
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "mode": mode,
            "parameters": params,
        }
        config_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        meta = identity | {
            "configuration_id": config_id,
            "strategy": experiment.strategy.id,
            "strategy_version": context["template"].version,
            "period": label,
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "scenario": scenario,
            "costs": costs.model_dump(),
        }
        if context["registry"].implementation(context["template"].name).lab_risk_parameters:
            meta["resolved_risk"] = parameter_risk(
                context["registry"].implementation(context["template"].name),
                context["template"].risk,
                params,
            ).model_dump(mode="json")
        if recovery and (saved := recovery.take(meta)) is not None:
            rows.append(saved)
            if len(rows) % 1000 == 0:
                print(f"Recovered {len(rows)}/{context['backtests']}", file=sys.stderr)
            return saved
        record = store.start(meta)
        try:
            result = evaluate(context, frame, market, mode, params, period, costs)
            row = (
                meta
                | summarize(result)
                | getattr(result, "diagnostics", {})
                | {
                    "backtest_id": record,
                    "status": "completed",
                    "long_contribution": sum(t.net_pnl for t in result.trades if t.side == "long"),
                    "short_contribution": sum(
                        t.net_pnl for t in result.trades if t.side == "short"
                    ),
                    "long_trades": sum(t.side == "long" for t in result.trades),
                    "short_trades": sum(t.side == "short" for t in result.trades),
                }
            )
            pd.DataFrame({"equity": result.equity, "exposure": result.exposure}).to_parquet(
                store.path / record / "equity.parquet"
            )
            store.finish(
                record,
                {
                    "metrics": row,
                    "equity_sha256": hashlib.sha256(
                        (store.path / record / "equity.parquet").read_bytes()
                    ).hexdigest(),
                    "trades": [asdict(t) for t in result.trades],
                    "rejections": [asdict(r) for r in result.rejections],
                },
            )
            rows.append(row)
            if len(rows) % 25 == 0:
                print(f"Completed {len(rows)}/{context['backtests']}", file=sys.stderr)
            return row
        except (ValueError, RuntimeError, ArithmeticError) as exc:
            store.finish(record, {"error": str(exc)}, "failed")
            rows.append(meta | {"backtest_id": record, "status": "failed", "error": str(exc)})
            raise

    try:
        for market, frame in zip(experiment.markets, context["frames"], strict=True):
            for mode in experiment.modes:
                periods = [
                    (k, getattr(experiment.validation, k)) for k in ("train", "validation", "test")
                ]
                periods += list(experiment.diagnostic_periods.items())
                for label, period in periods:
                    for params in context["parameters"]:
                        for scenario, costs in context["scenarios"].items():
                            one(frame, market, mode, params, label, period, scenario, costs)
                for index, fold in enumerate(experiment.validation.walk_forward):
                    training = []
                    for params in context["parameters"]:
                        for scenario, costs in context["scenarios"].items():
                            row = one(
                                frame,
                                market,
                                mode,
                                params,
                                f"wf_{index}_train",
                                fold.train,
                                scenario,
                                costs,
                            )
                            if scenario == "base":
                                training.append(row)
                    eligible = [r for r in training if r.get(experiment.ranking.metric) is not None]
                    if len(context["parameters"]) == 1:
                        # A predeclared fixed reference needs no ranking selection.
                        # Preserve undefined metrics and apply the usual report filters.
                        chosen = training[0]
                        if not eligible:
                            print(
                                f"wf_{index}: {market.symbol}/{mode}: fixed single candidate; "
                                f"{experiment.ranking.metric} undefined in TRAIN/base; "
                                "continuing without ranking, metrics and filters unchanged",
                                file=sys.stderr,
                            )
                    elif not eligible:
                        raise ValueError(
                            f"wf_{index}: training ranking metric undefined for all candidates"
                        )
                    else:
                        chosen = min(eligible, key=lambda row: rank_key(row, experiment))
                    for scenario, costs in context["scenarios"].items():
                        one(
                            frame,
                            market,
                            mode,
                            chosen["parameters"],
                            f"wf_{index}_test",
                            fold.test,
                            scenario,
                            costs,
                        )
        if recovery:
            recovery.assert_consumed()
        reports(store.path, experiment, rows, context, code)
        if recovery:
            note = (
                "\n## Recovery provenance\n\n"
                f"Source run: {recovery.source}\n\n"
                f"Reused verified backtests: {len(recovery.records)}; "
                f"new backtests: {len(rows) - len(recovery.records)}.\n\n"
                "Original IDs/hashes retained in ledger.sqlite. reuse.json locates original "
                "result.json/equity.parquet files; keep all referenced source directories. "
                "New artifacts use the current environment; source provenance is retained "
                "in its original directory and hashed in reuse.json.\n"
            )
            for filename in ("summary.md", "ai_summary.md"):
                with (store.path / filename).open("a", encoding="utf-8") as handle:
                    handle.write(note)
        write_json(store.path / "outcome.json", {"status": "COMPLETE", "backtests": len(rows)})
    except BaseException as exc:
        write_json(
            store.path / "outcome.json",
            {"status": "FAILED", "backtests": len(rows), "error": str(exc)},
        )
        if not (store.path / "ai_summary.md").exists():
            with (store.path / "ai_summary.md").open("x", encoding="utf-8") as handle:
                handle.write(
                    f"# FAILED: {experiment.experiment_id}\n\nRun: {store.run_id}\n"
                    f"Code hash: {code['code_sha256']}\n\nError: {exc}\n"
                    f"Recorded backtests: {len(rows)} / {context['backtests']}\n"
                    "No complete leaderboard is available. Inspect outcome.json, resolved.json "
                    "and ledger.sqlite; do not interpret partial results as completed research.\n"
                )
        raise
    return store.path
