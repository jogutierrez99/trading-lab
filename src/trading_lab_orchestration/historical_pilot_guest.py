"""Container worker for the exact six-case sealed Issue #3 job."""

import json
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from quant_lab.config import AppConfig, CostsConfig, RiskConfig, StrategyConfig
from quant_lab.execution_config import ExecutionConfig
from quant_lab.features import atr
from quant_lab.metrics import summarize
from quant_lab.strategies.btc_spot_sma50_sma200_1h_pilot_v1 import (
    BtcSpotSma50Sma2001hPilotV1Strategy,
)
from quant_lab.study_backend import Segment, StudyBackend

from .contracts import canonical, digest
from .historical_pilot_contract import (
    CANDLES,
    Job,
    encode_transport,
    hash_bytes,
    read_candles,
    window,
)
from .isolated_study_contract import DEPENDENCIES, PILOT_STRATEGY, Metrics


def calculate(frame, job, case):
    candles = window(frame, case)
    risk = job.plan.risk
    strategy = BtcSpotSma50Sma2001hPilotV1Strategy(
        StrategyConfig(
            name=PILOT_STRATEGY,
            version="1.0.0",
            parameters=job.plan.parameters,
            enabled=False,
        )
    )
    result = StudyBackend().run(
        candles,
        strategy.generate_signals(candles),
        atr(candles, 14) * 2,
        Segment(
            "BTCUSDT",
            "1h",
            pd.Timestamp(case.start).tz_convert("UTC"),
            pd.Timestamp(case.end).tz_convert("UTC"),
        ),
        AppConfig(starting_capital=risk.initial_cash, costs=CostsConfig(**case.costs.model_dump())),
        RiskConfig(
            risk_per_trade_pct=risk.risk_per_trade_pct,
            max_position_pct=risk.max_position_pct,
            max_exposure_pct=risk.max_exposure_pct,
            atr_period=14,
            atr_multiplier=2,
            risk_reward=2,
        ),
        ExecutionConfig(
            direction="long",
            market_mode="spot",
            liquidate_at_end=True,
            filter_assumption="Frozen Issue #3 bounds",
            quantity_step=risk.quantity_step,
            min_quantity=risk.min_quantity,
            min_notional=risk.min_notional,
        ),
    )
    if result.open_position is not None:
        raise ValueError("Historical segment must end flat")
    metrics = summarize(result)
    return json.loads(
        json.dumps(
            {
                "id": case.id,
                "segment": case.segment,
                "scenario": case.scenario,
                "costs": case.costs.model_dump(mode="json"),
                "metrics": {key: metrics[key] for key in Metrics.model_fields},
                "trades": [asdict(t) for t in result.trades],
                "rejections": [asdict(r) for r in result.rejections],
                "open_position": None,
                "equity": result.equity.tolist(),
                "exposure": result.exposure.tolist(),
            },
            default=lambda timestamp: timestamp.isoformat(),
            allow_nan=False,
        )
    )


def main():
    if Path.cwd() != Path("/work"):
        raise ValueError("Historical adapter requires the isolated guest")
    job = Job.model_validate_json(Path("historical-job.json").read_bytes())
    if job.plan.kind != "HISTORICAL_PROPOSAL":
        raise ValueError("Expected the Issue #3 six-case plan")
    if (
        digest(canonical({name: version(name) for name in DEPENDENCIES}))
        != job.plan.dependencies_sha256
    ):
        raise ValueError("Container dependency closure changed")
    for name, expected in job.closure.items():
        if hash_bytes(Path(name).read_bytes()) != expected:
            raise ValueError("Container input closure changed")
    frame = read_candles(Path(CANDLES).read_bytes(), job)
    transport = encode_transport(job, (calculate(frame, job, case) for case in job.plan.cases))
    print(transport.decode("utf-8"), end="")


if __name__ == "__main__":
    main()
