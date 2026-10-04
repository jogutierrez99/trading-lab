"""Frozen candidate lists and named historical falsification, using the lab backend."""

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import Field, model_validator

from quant_lab.config import CostsConfig, StrategyName, StrictModel, load_yaml
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.lab_runner import evaluate, parameter_risk, prepare
from quant_lab.lab_schema import Market, Mode, Period, Strategy
from quant_lab.metrics import summarize


class Candidate(StrictModel):
    candidate_id: StrategyName
    mode: Mode
    parameters: dict[str, Any]


class ChallengePeriod(Period):
    label: StrategyName


class HistoricalChallenge(StrictModel):
    label: Literal["HISTORICAL_CHALLENGE"] = "HISTORICAL_CHALLENGE"
    requested: Period
    warmup_start: datetime
    segments: list[ChallengePeriod] = Field(min_length=1)
    cost_stress: dict[StrategyName, CostsConfig]

    @model_validator(mode="after")
    def chronology(self):
        if (
            self.warmup_start.utcoffset() != timedelta(0)
            or self.warmup_start != self.requested.start
        ):
            raise ValueError("Warmup starts at requested UTC boundary")
        if (
            self.segments[0].start < self.requested.start
            or self.segments[-1].end != self.requested.end
        ):
            raise ValueError("Challenge segments must fit requested interval")
        if len({p.label for p in self.segments}) != len(self.segments):
            raise ValueError("Duplicate challenge segment")
        if any(
            a.end != b.start for a, b in zip(self.segments[:-1], self.segments[1:], strict=True)
        ):
            raise ValueError("Challenge segments must be contiguous and disjoint")
        if "base" in self.cost_stress or not self.cost_stress:
            raise ValueError("Explicit non-base cost stress required")
        return self

    @property
    def walk_forward(self):
        return []

    def periods(self):
        for segment in self.segments:
            yield f"HISTORICAL_CHALLENGE/{segment.label}", segment


class Challenge(StrictModel):
    schema_version: Literal[1] = 1
    experiment_id: StrategyName
    created_at: datetime
    description: str
    hypothesis_status: Literal["NEW_HYPOTHESIS"] = "NEW_HYPOTHESIS"
    selection_context: Literal["selected_using_previously_observed_test"]
    freeze_policy: Literal["no_parameter_changes_after_challenge"]
    app: str = "../app.yaml"
    strategy: Strategy
    markets: list[Market] = Field(min_length=1, max_length=1)
    candidates: list[Candidate] = Field(min_length=1)
    initial_cash: float = Field(default=10000.0, gt=0, allow_inf_nan=False)
    costs: CostsConfig
    execution: ExecutionConfig
    historical_challenge: HistoricalChallenge

    @model_validator(mode="after")
    def frozen(self):
        if self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be UTC")
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate candidate_id")
        if not self.execution.liquidate_at_end or self.execution.direction != "long":
            raise ValueError(
                "Independent periods require liquidation and candidate-controlled modes"
            )
        if self.execution.market_mode == "spot" and any(
            c.mode != "LONG_ONLY" for c in self.candidates
        ):
            raise ValueError("Short candidates require synthetic execution")
        step = (
            pd.Timedelta(minutes=15)
            if self.markets[0].timeframe == "15m"
            else pd.Timedelta(self.markets[0].timeframe)
        )
        earliest = self.historical_challenge.warmup_start + self.markets[0].warmup_bars * step
        if self.historical_challenge.segments[0].start != earliest:
            raise ValueError("First scored segment must follow exactly the declared warmup")
        return self

    # The existing prepare contract is reused for data, strategy, costs, warmup
    # and mode guards. No synthetic TRAIN/TEST periods are constructed.
    @property
    def validation(self):
        return self.historical_challenge

    @property
    def modes(self):
        return list(dict.fromkeys(c.mode for c in self.candidates))

    @property
    def strategy_parameters(self):
        return {}

    def grid(self):
        # Unique parameter dictionaries for prepare only, never a cartesian grid.
        seen = set()
        for candidate in self.candidates:
            key = json.dumps(candidate.parameters, sort_keys=True)
            if key not in seen:
                seen.add(key)
                yield candidate.parameters


def resolve_challenge(root: Path, identifier: str) -> tuple[Path, Challenge]:
    for path in sorted((root / "configs/challenges").glob("*.yaml")):
        spec = load_yaml(path, Challenge)
        if spec.experiment_id == identifier:
            return path, spec
    raise ValueError(f"Unknown challenge: {identifier}")


def prepare_challenge(path: Path, spec: Challenge, full: bool = False) -> dict:
    context = prepare(path, spec, full=full)
    context["execution"] = spec.execution
    cls = context["registry"].implementation(spec.strategy.id)
    resolved = []
    seen = set()
    for candidate in spec.candidates:
        params = cls.parameter_model.model_validate(
            context["template"].parameters | candidate.parameters
        ).model_dump()
        key = (candidate.mode, json.dumps(params, sort_keys=True))
        if key in seen:
            raise ValueError("Duplicate resolved candidate/mode")
        seen.add(key)
        resolved.append(
            {
                "candidate_id": candidate.candidate_id,
                "mode": candidate.mode,
                "parameters": params,
                "risk": parameter_risk(cls, context["template"].risk, params).model_dump(
                    mode="json"
                ),
            }
        )
    context["candidates"] = resolved
    context["backtests"] = (
        len(resolved) * len(spec.historical_challenge.segments) * len(context["scenarios"])
    )
    return context


def run_challenge(path: Path, spec: Challenge, root: Path) -> Path:
    context = prepare_challenge(path, spec, full=True)
    code = provenance(root)
    plan = spec.model_dump(mode="json")
    store = ExperimentStore(root / "results" / spec.experiment_id, plan, code)
    write_json(
        store.path / "run.json",
        {
            "kind": "lab_challenge_v1",
            "experiment_id": spec.experiment_id,
            "run_id": store.run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "expected_backtests": context["backtests"],
        },
    )
    write_json(
        store.path / "resolved.json",
        {
            "app": context["app"].model_dump(mode="json"),
            "strategy": context["template"].model_dump(mode="json"),
            "parameters": context["parameters"],
            "candidates": context["candidates"],
            "datasets": context["datasets"],
            "backend": "study_backend_v1",
            "execution": spec.execution.model_dump(mode="json"),
            "historical_challenge": spec.historical_challenge.model_dump(mode="json"),
        },
    )
    with (store.path / "experiment_snapshot.yaml").open("x", encoding="utf-8") as handle:
        handle.write(path.read_text(encoding="utf-8"))
    write_json(store.path / "environment.json", code)
    rows = []
    market, frame = spec.markets[0], context["frames"][0]
    print(f"HISTORICAL_CHALLENGE {store.run_id}: {context['backtests']} backtests", file=sys.stderr)
    try:
        for candidate in context["candidates"]:
            identity = {
                "symbol": market.symbol,
                "timeframe": market.timeframe,
                "mode": candidate["mode"],
                "parameters": candidate["parameters"],
            }
            config_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[
                :16
            ]
            for label, period in spec.historical_challenge.periods():
                for scenario, costs in context["scenarios"].items():
                    meta = identity | {
                        "configuration_id": config_id,
                        "candidate_id": candidate["candidate_id"],
                        "strategy": spec.strategy.id,
                        "strategy_version": context["template"].version,
                        "period": label,
                        "start": period.start.isoformat(),
                        "end": period.end.isoformat(),
                        "scenario": scenario,
                        "costs": costs.model_dump(),
                        "resolved_risk": candidate["risk"],
                    }
                    record = store.start(meta)
                    result = evaluate(
                        context,
                        frame,
                        market,
                        candidate["mode"],
                        candidate["parameters"],
                        period,
                        costs,
                    )
                    row = meta | summarize(result) | {"backtest_id": record, "status": "completed"}
                    equity = store.path / record / "equity.parquet"
                    pd.DataFrame({"equity": result.equity, "exposure": result.exposure}).to_parquet(
                        equity
                    )
                    store.finish(
                        record,
                        {
                            "metrics": row,
                            "equity_sha256": hashlib.sha256(equity.read_bytes()).hexdigest(),
                            "trades": [asdict(t) for t in result.trades],
                            "rejections": [asdict(r) for r in result.rejections],
                        },
                    )
                    rows.append(row)
                    print(f"Completed {len(rows)}/{context['backtests']}", file=sys.stderr)
        serial = [
            r
            | {
                "parameters": json.dumps(r["parameters"], sort_keys=True),
                "costs": json.dumps(r["costs"], sort_keys=True),
            }
            for r in rows
        ]
        pd.DataFrame(serial).to_csv(store.path / "metrics.csv", index=False, mode="x")
        write_json(
            store.path / "summary.json",
            {
                "scope": "HISTORICAL_CHALLENGE",
                "total_backtests": len(rows),
                "research_classification": None,
                "reason": "Not independent OOS; no parameter selection",
                "candidates": context["candidates"],
            },
        )
        text = (
            f"# HISTORICAL_CHALLENGE: {spec.experiment_id}\n\nRun: {store.run_id}\n\n"
            "Frozen candidates selected using already observed TEST. "
            "Earlier history is falsification, "
            "not a new independent holdout. No ranking, grid or parameter changes.\n\n"
            "Natural calendar segments reset capital independently; returns are not compounded. "
            "Initial warmup is excluded from scored evidence. Costs/risk/backend unchanged.\n\n"
            "This report does not confer RESEARCH_PASS/OOS_PASS/ROBUST_PASS/paper eligibility. "
            "Historical results do not establish future profitability.\n\n```csv\n"
            + pd.DataFrame(serial)[
                [
                    "candidate_id",
                    "period",
                    "scenario",
                    "mode",
                    "closed_trades",
                    "return_pct",
                    "profit_factor",
                    "sharpe",
                    "expectancy",
                    "max_drawdown_pct",
                ]
            ].to_csv(index=False)
            + "```\n"
        )
        for filename in ("summary.md", "ai_summary.md"):
            with (store.path / filename).open("x", encoding="utf-8") as handle:
                handle.write(text)
        write_json(store.path / "outcome.json", {"status": "COMPLETE", "backtests": len(rows)})
    except BaseException as exc:
        write_json(
            store.path / "outcome.json",
            {"status": "FAILED", "backtests": len(rows), "error": str(exc)},
        )
        raise
    return store.path
