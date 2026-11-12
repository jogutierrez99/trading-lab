"""Prepare and verify the two branches of the sealed RMM TRAIN/VALIDATION comparison."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .workspaces import file_hash, inventory, write_json

BASELINE_ID = "risk_managed_momentum_v1_btc_eth_4h"
BASELINE_STRATEGY = "risk_managed_momentum_v1"
BASELINE_VERSION = "1.0.0"
BASELINE_EXPERIMENT = f"configs/experiments/{BASELINE_ID}.yaml"
BASELINE_PROFILE = f"configs/strategies/{BASELINE_STRATEGY}.yaml"
BASELINE_FILES = (
    BASELINE_EXPERIMENT,
    BASELINE_PROFILE,
    f"src/quant_lab/strategies/{BASELINE_STRATEGY}.py",
    "configs/app.yaml",
    "configs/risk.yaml",
)
VARIANT = "rmm_4h_momentum_28d_filter_v1"
ASSETS = ("BTCUSDT", "ETHUSDT")
MODES = ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT")
PER_BRANCH = 12


def comparison_identity(implementation, selection):
    if (
        (selection.task_id, selection.candidate_id, selection.hypothesis_sha256)
        != (implementation.task_id, implementation.candidate_id, implementation.hypothesis_sha256)
        or selection.baseline_commit != implementation.base_commit
        or implementation.hypothesis_manifest.hypothesis_id != VARIANT
        or implementation.plan.operation != "NEW_STRATEGY"
        or implementation.plan.target != VARIANT
    ):
        raise ValueError("RMM comparison task, baseline revision or variant evidence mismatch")


def _scoped_bundle(workspace, pin, market, left, end):
    import pandas as pd

    from quant_lab.lab_data import inspect_bundle
    from quant_lab.literature_data import write_bundle

    info = inspect_bundle(workspace, market.model_copy(update={"dataset": pin.path}))
    if (
        "audit" not in info["manifest"]
        or info["dataset_id"] != pin.dataset_id
        or info["parquet_sha256"] != pin.parquet_sha256
    ):
        raise ValueError("RMM requires the pinned 4h price bundle")
    frame = pd.read_parquet(
        Path(pin.path) / "candles.parquet",
        filters=[("open_time", ">=", left), ("open_time", "<", end)],
    )
    expected = pd.date_range(left, end, freq="4h", inclusive="left", name="open_time")
    if not frame.index.equals(expected):
        raise ValueError("RMM source has gaps or missing warmup in the selected window")
    origin = {
        "dataset_id": pin.dataset_id,
        "manifest_sha256": pin.manifest_sha256,
        "parquet_sha256": pin.parquet_sha256,
        "kind": pin.kind,
        "window_start": left.isoformat(),
        "window_end_exclusive": end.isoformat(),
    }
    return write_bundle(workspace, market.symbol, "4h", frame, origin)


def prepare_comparison_inputs(root, attempt, implementation, receipt, plan):
    import shutil

    import pandas as pd
    import yaml

    from quant_lab.config import AppConfig, _read_mapping, load_yaml
    from quant_lab.lab_schema import Experiment

    from .execution_inputs import archive_base, relative_file, verify_hashes

    selection = plan.comparison
    comparison_identity(implementation, selection)
    source = Path(plan.experiment).resolve()
    if (
        source != (Path(attempt["repo"]) / BASELINE_EXPERIMENT).resolve()
        or set(selection.baseline_files) != set(BASELINE_FILES)
        or plan.experiment_sha256 != selection.baseline_files[BASELINE_EXPERIMENT]
    ):
        raise ValueError("RMM requires the frozen baseline configuration and code pins")
    workspace = root / "workspace"
    archive_base(attempt, workspace)
    verify_hashes({str(workspace / name): sha for name, sha in selection.baseline_files.items()})
    if file_hash(source) != plan.experiment_sha256:
        raise ValueError("Checkout baseline differs from the pinned baseline")
    baseline = load_yaml(workspace / BASELINE_EXPERIMENT, Experiment)
    app = load_yaml(workspace / "configs/app.yaml", AppConfig)
    manifest = implementation.hypothesis_manifest
    if (
        baseline.experiment_id != BASELINE_ID
        or baseline.strategy.id != BASELINE_STRATEGY
        or (source.parent / baseline.strategy.config).resolve()
        != (Path(attempt["repo"]) / BASELINE_PROFILE).resolve()
        or (source.parent / baseline.app).resolve()
        != (Path(attempt["repo"]) / "configs/app.yaml").resolve()
        or app.risk_file != "risk.yaml"
        or baseline.combinations != 1
        or tuple(m.symbol for m in baseline.markets) != ASSETS
        or tuple(baseline.modes) != MODES
        or baseline.execution.market_mode != manifest.execution_assumptions.market_mode
        or baseline.execution.market_mode != "synthetic"
        or manifest.data_requirements.funding_policy != "NOT_MODELLED"
        or set(manifest.data_requirements.assets) != set(ASSETS)
    ):
        raise ValueError("RMM baseline identity, markets or execution assumptions diverge")
    base_cost = (baseline.costs or app.costs).model_dump()
    if any(getattr(manifest.execution_assumptions, key) != val for key, val in base_cost.items()):
        raise ValueError("RMM BASE costs differ from the sealed card")
    evaluation = manifest.evaluation_plan
    if evaluation.train.end != evaluation.validation.start:
        raise ValueError("RMM TRAIN and VALIDATION must be contiguous")
    raw = baseline.model_dump()
    raw["validation"] = {
        name: getattr(evaluation, name).model_dump() for name in ("train", "validation", "test")
    }
    raw["diagnostic_periods"] = {}
    raw["costs"] = base_cost
    raw["app"] = "../configs/app.yaml"
    raw["strategy"]["config"] = "../" + BASELINE_PROFILE
    inputs = {str(source): plan.experiment_sha256}
    pins = {pin.dataset_id: pin for pin in plan.datasets}
    if len(pins) != 2 or set(pins) != {m.dataset_id for m in baseline.markets}:
        raise ValueError("Pin exactly the BTC and ETH baseline datasets")
    for market in baseline.markets:
        pin = pins[market.dataset_id]
        parquet = str(Path(pin.path) / "candles.parquet")
        metadata = str(Path(pin.path) / "manifest.json")
        if (
            market.timeframe != "4h"
            or market.dataset_format != "bundle"
            or market.perpetual_data is not None
            or market.warmup_bars != manifest.data_requirements.warmup_bars
            or Path(pin.path).resolve() != (source.parent / market.dataset).resolve()
            or not any(
                ref.startswith(f"{market.symbol} 4h | dataset_id={pin.dataset_id} | ")
                for ref in manifest.data_requirements.dataset_refs
            )
        ):
            raise ValueError("RMM pinned datasets or warmup diverge from the sealed card")
        for name, sha in [
            *pin.provenance_files.items(),
            (parquet, pin.parquet_sha256),
            (metadata, pin.manifest_sha256),
        ]:
            path = Path(name)
            if not path.is_absolute() or inputs.setdefault(str(path.resolve()), sha) != sha:
                raise ValueError("RMM dataset provenance is contradictory or relative")
    if sum(Path(name).stat().st_size for name in inputs) > plan.max_dataset_bytes:
        raise ValueError("RMM source byte volume exceeds the plan")
    verify_hashes(inputs)

    if set(receipt["files"]) != set(implementation.plan.paths()):
        raise ValueError("RMM variant receipt does not identify the delivered files")
    for name, sha in receipt["files"].items():
        original = relative_file(Path(attempt["workspace"]), name)
        destination = relative_file(workspace, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(original.read_bytes())
        if file_hash(destination) != sha:
            raise ValueError("RMM variant delivery changed")
    trusted_runner = Path(__file__).resolve().parents[1] / "quant_lab"
    runner_files = {}
    for name in ("lab_runner.py", "lab_data.py", "lab_reporting.py"):
        target = workspace / "src/quant_lab" / name
        shutil.copyfile(trusted_runner / name, target)
        runner_files[target.relative_to(workspace).as_posix()] = file_hash(target)
    for raw_market, market in zip(raw["markets"], baseline.markets, strict=True):
        left = pd.Timestamp(evaluation.train.start) - pd.Timedelta(hours=4 * market.warmup_bars)
        scoped = _scoped_bundle(
            workspace,
            pins[market.dataset_id],
            market,
            left,
            pd.Timestamp(evaluation.validation.end),
        )
        raw_market.update(dataset=str(scoped), dataset_id=scoped.name)
    verify_hashes(inputs)

    config = workspace / "execution-config"
    config.mkdir()
    profile = _read_mapping(workspace / implementation.plan.paths()[1])
    if profile.get("enabled", False) or not plan.enable_execution_copy:
        raise ValueError(
            "RMM variant must be disabled in delivery and enabled only in execution copy"
        )
    profile["enabled"] = True
    variant = raw | {
        "experiment_id": VARIANT,
        "strategy": {"id": VARIANT, "config": "strategy.yaml"},
    }
    for name, value in (
        ("baseline.yaml", raw),
        ("experiment.yaml", variant),
        ("strategy.yaml", profile),
    ):
        with (config / name).open("x", encoding="utf-8") as handle:
            yaml.safe_dump(value, handle, sort_keys=False)
    write_json(root / "implementation-receipt.json", receipt)
    write_json(
        root / "adaptations.json",
        {
            "baseline": {
                "experiment_id": BASELINE_ID,
                "strategy": BASELINE_STRATEGY,
                "version": BASELINE_VERSION,
                "commit": selection.baseline_commit,
                "files": selection.baseline_files,
            },
            "variant": {
                "strategy": VARIANT,
                "files": receipt["files"],
                "execution_copy_enabled": True,
            },
            "shared_runner_files": runner_files,
            "selected_periods": list(selection.periods),
            "excluded": ["test", "walk_forward", "diagnostics", "adverse"],
        },
    )
    return inputs, inventory(workspace)


def verify_parity(experiments, contexts):
    import pandas as pd

    from quant_lab.config import MarketConfig
    from quant_lab.lab_runner import parameter_risk, window

    baseline, variant = experiments
    left, right = contexts
    if (
        baseline.strategy.id != BASELINE_STRATEGY
        or variant.strategy.id != VARIANT
        or left["template"].version != BASELINE_VERSION
        or baseline.model_dump(exclude={"experiment_id", "strategy"})
        != variant.model_dump(exclude={"experiment_id", "strategy"})
        or left["template"].model_dump(exclude={"name", "version"})
        != right["template"].model_dump(exclude={"name", "version"})
        or any(left[key] != right[key] for key in ("app", "parameters", "scenarios", "datasets"))
        or left["backtests"] != PER_BRANCH
        or right["backtests"] != PER_BRANCH
    ):
        raise ValueError("RMM comparison branches have divergent configuration or identity")
    base_cls = left["registry"].implementation(BASELINE_STRATEGY)
    variant_cls = right["registry"].implementation(VARIANT)
    if not issubclass(variant_cls, base_cls) or any(
        getattr(variant_cls, name) != getattr(base_cls, name)
        for name in (
            "lab_risk_parameters",
            "lab_price_levels",
            "lab_extended_metrics",
            "lab_entry_diagnostics",
        )
    ):
        raise ValueError(
            "RMM variant must extend the frozen baseline with unchanged sizing bindings"
        )
    for market, frame in zip(baseline.markets, left["frames"], strict=True):
        config = {
            "market": MarketConfig(symbol=market.symbol.replace("USDT", "/USDT"), timeframe="4h"),
            "parameters": left["parameters"][0],
            "risk": parameter_risk(base_cls, left["template"].risk, left["parameters"][0]),
        }
        base_strategy = base_cls(left["template"].model_copy(update=config))
        variant_strategy = variant_cls(right["template"].model_copy(update=config))
        for name in ("train", "validation"):
            candles, _ = window(frame, market, getattr(baseline.validation, name))
            base = base_strategy.generate_signals(candles.copy(deep=True))
            filtered = variant_strategy.generate_signals(candles.copy(deep=True))
            daily = candles.close.resample("1D").agg(["size", "last"])
            close = daily["last"].where(daily["size"] == 6)
            momentum = (close / close.shift(28) - 1).where(close.rolling(29).count() == 29)
            decision = candles.index + pd.Timedelta(hours=4)
            eligible_day = (decision - pd.Timedelta(nanoseconds=1)).normalize() - pd.Timedelta(
                days=1
            )
            eligible = momentum.reindex(eligible_day).to_numpy()
            if (
                filtered.long_exits != base.long_exits
                or filtered.short_exits != base.short_exits
                or filtered.long_entries != tuple(pd.Series(base.long_entries) & (eligible > 0))
                or filtered.short_entries != tuple(pd.Series(base.short_entries) & (eligible < 0))
            ):
                raise ValueError(
                    "RMM variant differs from the specified entry filter or baseline exits"
                )


def paired_metrics(baseline_run, variant_run):
    def rows(run, strategy):
        from .execution_inputs import relative_file

        with closing(
            sqlite3.connect((run / "ledger.sqlite").as_uri() + "?mode=ro", uri=True)
        ) as conn:
            records = conn.execute(
                "SELECT id,status,result_sha256,metadata FROM experiments LIMIT ?",
                (PER_BRANCH + 1,),
            ).fetchall()
        values = []
        for identifier, status, sha, metadata in records:
            path = relative_file(run, identifier + "/result.json")
            if status != "completed" or file_hash(path) != sha:
                raise ValueError("RMM branch ledger is incomplete or its evidence changed")
            document = json.loads(path.read_text())
            row = document["metrics"]
            if row["backtest_id"] != identifier or any(
                row[key] != value for key, value in json.loads(metadata).items()
            ):
                raise ValueError("RMM branch result contradicts its ledger")
            if (
                len(document["trades"]) != row["closed_trades"]
                or file_hash(relative_file(run, identifier + "/equity.parquet"))
                != document["equity_sha256"]
            ):
                raise ValueError("RMM branch trades or equity contradict the result")
            values.append(row)
        expected = {
            (asset, mode, period)
            for asset in ASSETS
            for mode in MODES
            for period in ("train", "validation")
        }
        keys = {(row["symbol"], row["mode"], row["period"]): row for row in values}
        if (
            set(keys) != expected
            or len(values) != PER_BRANCH
            or any(
                (r["strategy"], r["timeframe"], r["scenario"], r["status"])
                != (strategy, "4h", "base", "completed")
                for r in values
            )
        ):
            raise ValueError("RMM branch evidence has wrong identity or case coverage")
        return keys

    baseline = rows(baseline_run, BASELINE_STRATEGY)
    variant = rows(variant_run, VARIANT)
    fields = (
        "sharpe",
        "return_pct",
        "max_drawdown_pct",
        "average_close_exposure_pct",
        "closed_trades",
    )
    pairs = []
    for key, before in sorted(baseline.items()):
        after = variant[key]
        shared = ("start", "end", "costs", "parameters", "resolved_risk")
        if any(before[field] != after[field] for field in shared):
            raise ValueError("RMM results do not share windows, parameters, costs and risk")
        values = {
            label: {field: row[field] for field in fields}
            for label, row in (("baseline", before), ("variant", after))
        }
        a, b = values["baseline"]["sharpe"], values["variant"]["sharpe"]
        pairs.append(
            dict(zip(("asset", "mode", "period"), key, strict=True))
            | values
            | {
                "delta_sharpe": b - a if a is not None and b is not None else None,
            }
        )
    return pairs


def comparison_report(root, request, variant, result, approval):
    if any(
        report.get("baseline_backtests") != PER_BRANCH
        or report.get("total_backtests") != 2 * PER_BRANCH
        or report.get("periods") != list(request.plan.comparison.periods)
        for report in (result, approval)
    ):
        raise ValueError("RMM runner report does not support the 24-case scope")
    baseline_runs = list((root / "comparison-baseline").glob("*/*/run.json"))
    if len(baseline_runs) != 1:
        raise ValueError("RMM requires exactly one separately identified baseline run")
    baseline = baseline_runs[0].parent
    branches = {}
    resolved = {}
    for label, run, expected, strategy, config in (
        ("baseline", baseline, BASELINE_ID, BASELINE_STRATEGY, "baseline.yaml"),
        ("variant", variant, VARIANT, VARIANT, "experiment.yaml"),
    ):
        if run.parent.name != expected or json.loads((run / "outcome.json").read_text()) != {
            "status": "COMPLETE",
            "backtests": PER_BRANCH,
        }:
            raise ValueError("RMM branch run identity or outcome mismatch")
        meta = json.loads((run / "run.json").read_text())
        if (meta["experiment_id"], meta["run_id"], meta["expected_backtests"]) != (
            expected,
            run.name,
            PER_BRANCH,
        ):
            raise ValueError("RMM branch native metadata mismatch")
        native_plan = json.loads((run / "plan.json").read_text())
        resolved[label] = json.loads((run / "resolved.json").read_text())
        if (
            native_plan["experiment_id"] != expected
            or native_plan["strategy"]["id"] != strategy
            or resolved[label]["strategy"]["name"] != strategy
            or native_plan.get("selected_periods") != list(request.plan.comparison.periods)
            or file_hash(run / "experiment_snapshot.yaml")
            != file_hash(Path(request.experiment).with_name(config))
        ):
            raise ValueError("RMM native plan/configuration belongs to another branch")
        branches[label] = {
            "run_id": run.name,
            "experiment_id": expected,
            "strategy_version": resolved[label]["strategy"]["version"],
            "run_directory": run.relative_to(root).as_posix(),
            "sha256": {
                name: file_hash(run / name)
                for name in (
                    "run.json",
                    "outcome.json",
                    "ledger.sqlite",
                    "resolved.json",
                    "plan.json",
                    "experiment_snapshot.yaml",
                    "provenance.json",
                )
            },
        }
    if baseline.resolve() != Path(result["baseline_run_directory"]).resolve():
        raise ValueError("RMM worker baseline path mismatch")
    if any(
        resolved["baseline"][key] != resolved["variant"][key]
        for key in ("app", "parameters", "parameter_risks", "datasets", "backend", "execution")
    ):
        raise ValueError("RMM native branch configurations diverged")
    return {
        "scope": request.plan.scope,
        "task_id": request.task_id,
        "candidate_id": request.candidate_id,
        "execution_id": request.execution_id,
        "backtests": 2 * PER_BRANCH,
        "periods": list(request.plan.comparison.periods),
        "scenario": "base",
        "branches": branches,
        "baseline_provenance": json.loads((root / "adaptations.json").read_text())["baseline"],
        "variant_provenance": {
            "implementation_id": request.implementation_id,
            "receipt_sha256": request.implementation_receipt_sha256,
            "files": request.implementation_final_files,
        },
        "dataset_pins": [pin.model_dump(mode="json") for pin in request.plan.datasets],
        "pending": ["TEST", "ADVERSE", "SMA28", "RANDOM_CONTROL"],
        "paired_metrics": paired_metrics(baseline, variant),
    }


def verify_comparison_results(root, request, variant, result, approval):
    report = comparison_report(root, request, variant, result, approval)
    path = root / "comparison.json"
    if not path.exists():
        write_json(path, report)
    elif json.loads(path.read_text()) != report:
        raise ValueError("RMM comparison report changed")
