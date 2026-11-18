"""Container-only adapter from the sealed synthetic fixture to StudyBackend."""

import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from quant_lab.config import AppConfig, CostsConfig, RiskConfig
from quant_lab.execution_config import ExecutionConfig
from quant_lab.features import atr
from quant_lab.metrics import summarize
from quant_lab.strategies.base import Signals
from quant_lab.study_backend import Segment, StudyBackend

from .contracts import canonical, digest
from .isolated_study_contract import DATA, DEPENDENCIES, Metrics, Plan


def _case(fixture, plan, case):
    frame = pd.DataFrame(
        fixture["ohlcv"],
        columns=("open", "high", "low", "close", "volume"),
        index=pd.date_range(
            pd.Timestamp(fixture["start"]).tz_convert(UTC), periods=len(fixture["ohlcv"]), freq="h"
        ),
        dtype=float,
    )
    start, end = (pd.Timestamp(value).tz_convert(UTC) for value in (case.start, case.end))
    if (
        len(frame) != case.bars + case.warmup
        or frame.index[case.warmup] != start
        or frame.index[-1] + pd.Timedelta(hours=1) != end
    ):
        raise ValueError("Synthetic frame does not match the sealed window")
    signals = Signals(
        tuple(i in fixture["long_entries"] for i in range(len(frame))),
        tuple(i in fixture["long_exits"] for i in range(len(frame))),
        (False,) * len(frame),
        (False,) * len(frame),
    )
    risk = plan.risk
    distances = atr(frame, risk.atr_period) * risk.atr_multiplier
    result = StudyBackend().run(
        frame,
        signals,
        distances,
        Segment(plan.symbol, plan.timeframe, start, end),
        AppConfig(starting_capital=risk.initial_cash, costs=CostsConfig(**case.costs.model_dump())),
        RiskConfig(
            risk_per_trade_pct=risk.risk_per_trade_pct,
            max_position_pct=risk.max_position_pct,
            max_exposure_pct=risk.max_exposure_pct,
            atr_period=risk.atr_period,
            atr_multiplier=risk.atr_multiplier,
            risk_reward=risk.risk_reward,
        ),
        ExecutionConfig(
            quantity_step=risk.quantity_step,
            min_quantity=risk.min_quantity,
            min_notional=risk.min_notional,
            filter_assumption="Synthetic fixture",
        ),
    )
    if result.open_position is not None:
        raise ValueError("Expected a liquidated segment")
    metrics = summarize(result)
    return {
        "id": case.id,
        "segment": case.segment,
        "scenario": case.scenario,
        "costs": case.costs.model_dump(mode="json"),
        "metrics": {key: metrics[key] for key in Metrics.model_fields},
        "trades": [asdict(t) for t in result.trades],
        "rejections": [asdict(r) for r in result.rejections],
        "open_position": result.open_position,
        "equity": result.equity.tolist(),
        "exposure": result.exposure.tolist(),
    }


def main():
    if Path.cwd() != Path("/work") or not sys.platform.startswith("linux"):
        raise ValueError("Synthetic StudyBackend adapter requires the isolated guest")
    plan = Plan.model_validate_json(Path("plan.json").read_bytes())
    if plan.kind != "SYNTHETIC_ACCEPTANCE" or set(plan.parameters):
        raise ValueError("Historical calculations are not available")
    if (
        digest(canonical({name: version(name) for name in DEPENDENCIES}))
        != plan.dependencies_sha256
    ):
        raise ValueError("Container dependencies changed")
    for name, h in plan.input_files.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != h:
            raise ValueError("Container input seal mismatch")
    data = Path(DATA).read_bytes()
    if hashlib.sha256(data).hexdigest() != plan.dataset_sha256:
        raise ValueError("Synthetic dataset seal mismatch")
    fixture = json.loads(data)
    files = {f"cases/{case.id}.json": _case(fixture, plan, case) for case in plan.cases}
    files = json.loads(json.dumps(files, default=lambda timestamp: timestamp.isoformat()))
    result = {
        "schema_version": "1.1",
        "status": "COMPLETE",
        "job_id": plan.job_id,
        "plan_sha256": digest(canonical(plan.model_dump(mode="json"))),
        "image": plan.image,
        "engine_sha256": plan.engine_sha256,
        "dataset_sha256": plan.dataset_sha256,
        "dependencies_sha256": plan.dependencies_sha256,
        "files": files,
        "sha256": {name: digest(canonical(value)) for name, value in files.items()},
    }
    print(canonical(result))


if __name__ == "__main__":
    main()
