"""Independent, signal-only Donchian protocol; never accepted by the legacy runner."""

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import Field

from quant_lab.brokers.instruments import Instrument
from quant_lab.config import CostsConfig, RiskConfig, StrategyConfig, StrictModel, load_yaml
from quant_lab.eth_donchian_review import load_protocol
from quant_lab.execution_config import ExecutionConfig
from quant_lab.lab_evidence import sha256
from quant_lab.strategies.donchian_atr_breakout import DonchianAtrBreakoutStrategy

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = "results/forward/eth_donchian_short_1h"
DEFAULT = ROOT / "configs/forward/okx_demo_eth_donchian_short_1h.yaml"
IDS = [f"donchian_atr_{i:02d}" for i in range(6)]


class DonchianConfig(StrictModel):
    schema_version: Literal[1] = 1
    study_id: Literal["eth_donchian_short_prospective_v1"]
    broker: Literal["okx"] = "okx"
    environment: Literal["demo"] = "demo"
    mode: Literal["signal_only"]
    trading_enabled: Literal[False]
    send_orders: Literal[False]
    allow_live_trading: Literal[False]
    symbol: Literal["ETHUSDT"]
    timeframe: Literal["1h"]
    direction: Literal["SHORT_ONLY"]
    strategy_version: Literal["1.0.0"]
    instrument: str = "AUTO"
    candidates: list[str]
    warmup_bars: Literal[1000]
    output: Literal["../../results/forward/eth_donchian_short_1h"]
    poll_seconds: float = Field(default=2.0, ge=1, le=10, allow_inf_nan=False)
    maximum_open_latency_seconds: Literal[90] = 90
    heartbeat_seconds: Literal[300] = 300


def frozen_context(root=ROOT):
    protocol = load_protocol(root)
    publication = root / protocol.recent_publication
    sources = json.loads((publication / "sources.json").read_text(encoding="utf-8"))
    source = next(s for s in sources if s["family"] == "donchian_atr")
    if (
        sha256(publication / "sources.json")
        != json.loads((publication / "metadata.json").read_text(encoding="utf-8"))[
            "artifacts_sha256"
        ]["sources.json"]
    ):
        raise ValueError("Frozen candidate publication changed")
    template = StrategyConfig.model_validate(source["resolved_strategy"])
    candidates = {}
    for name, parameters, risk in zip(
        IDS, source["parameters"], source["parameter_risks"], strict=True
    ):
        config = template.model_copy(update={"parameters": parameters})
        candidates[name] = (DonchianAtrBreakoutStrategy(config), RiskConfig.model_validate(risk))
    if len(candidates) != 6:
        raise ValueError("Expected six frozen candidates")
    costs = {"base": CostsConfig.model_validate(source["cost_assumptions"]["base"])}
    costs["adverse"] = CostsConfig.model_validate(source["cost_assumptions"]["stress"]["adverse"])
    return protocol, candidates, costs, source


def load(path=DEFAULT, root=ROOT):
    config = load_yaml(path, DonchianConfig)
    if config.candidates != IDS:
        raise ValueError("Observe all six frozen candidates in original order")
    if config.instrument != "AUTO" and not config.instrument.startswith("ETH-"):
        raise ValueError("Only ETH instruments permitted")
    output = (Path(path).resolve().parent / config.output).resolve()
    if output != root.resolve() / OUTPUT:
        raise ValueError("Dedicated Donchian output must not alias another forward journal")
    context = frozen_context(root)
    return config, output, context


def select_instrument(config, broker, now):
    """Public discovery; expiry and currency are part of immutable stream identity."""
    matches = []
    for row in broker.get_instruments():
        if not row.get("instId", "").startswith("ETH-"):
            continue
        try:
            inst = Instrument.parse(row)
            expiry = pd.Timestamp(int(row["expTime"]), unit="ms", tz="UTC")
            if (
                row.get("ctMult") != "1"
                # OKX quoteCcy applies to SPOT/MARGIN and is empty on X-Perps.
                # Instrument.parse validates the derivative's settlement currency;
                # preserve the raw quote field instead of inventing a replacement.
                or row.get("quoteCcy") not in {"", "USD", "USDC"}
                or expiry <= now + pd.Timedelta(days=180)
            ):
                continue
            if config.instrument != "AUTO" and inst.instrument_id != config.instrument:
                continue
            matches.append((expiry, inst.instrument_id, inst, row))
        except (ValueError, KeyError, TypeError):
            continue
    if not matches:
        raise ValueError("SIGNAL_ONLY_BLOCKED: no eligible ETH linear EEA X-Perp metadata")
    _, _, inst, row = max(matches, key=lambda r: (r[0], r[1]))
    return inst, {
        k: row.get(k)
        for k in (
            "instId",
            "instType",
            "ruleType",
            "ctType",
            "ctVal",
            "ctMult",
            "ctValCcy",
            "quoteCcy",
            "settleCcy",
            "lotSz",
            "minSz",
            "tickSz",
            "expTime",
            "state",
        )
    }


def execution(inst, source):
    original = source["execution_assumptions"]
    step = inst.contract_size * inst.lot_size
    lab_step = Decimal(str(original["quantity_step"]))
    if step % lab_step:
        raise ValueError("OKX base lot is incompatible with frozen lab quantity lattice")
    return ExecutionConfig(
        market_mode="synthetic",
        direction="short",
        quantity_step=float(step),
        min_quantity=max(original["min_quantity"], float(inst.contract_size * inst.min_size)),
        min_notional=original["min_notional"],
        liquidate_at_end=False,
        filter_assumption="Frozen risk/costs with documented OKX base-lot rounding; no orders",
    )


def resolved(config, inst, metadata, context):
    protocol, candidates, costs, source = context
    return dict(
        forward=config.model_dump(mode="json") | {"data_protocol": "donchian_short_1h"},
        instrument=asdict(inst),
        instrument_metadata=metadata,
        candidates={
            n: dict(parameters=s.parameters.model_dump(), risk=r.model_dump())
            for n, (s, r) in candidates.items()
        },
        costs={n: c.model_dump() for n, c in costs.items()},
        execution=execution(inst, source).model_dump(),
        initial_cash=source["original_plan"]["initial_cash"],
        nominal_start=protocol.earliest_signal_close_utc,
        protocol_sha256=sha256(ROOT / "configs/research/eth_donchian_short_prospective_v1.yaml"),
        price_basis="OKX contract trade candles; not Binance USD-M, mark, index or ticker",
    )
