"""Pinned historical references and numerical baseline equality, without writes."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from quant_lab.batch_006_analysis import metrics
from quant_lab.config import StrictModel, load_yaml
from quant_lab.cross_market_study import clean_json
from quant_lab.entry_timing_execution import CASES
from quant_lab.mtf_series import schedule
from quant_lab.new_mtf_runner import frozen_protocol, matched_data, read_json, sha, verify_artifacts

DEFAULT_CONFIG = Path("configs/profiles/entry_timing_15m.yaml")


class CaseConfig(StrictModel):
    asset: Literal["ETHUSDT"]
    family: Literal["supertrend_pullback", "roc_momentum"]
    architecture: Literal["V1", "V2"]
    execution_policy: Literal["TIMING_15M_SUPERTREND", "TIMING_15M_ROC"]


class Protocol(StrictModel):
    schema_version: Literal[1]
    source_run: str
    source_manifest_sha256: str
    configurations: list[CaseConfig]
    expiry_bars: Literal[4]
    max_extension_atr: Literal[1.5]
    consolidation_bars: Literal[3]
    consolidation_atr_multiple: Literal[2.0]


def load_protocol(repo, config=DEFAULT_CONFIG):
    protocol = load_yaml(repo / config, Protocol)
    expected = [
        (a, f, v, "TIMING_15M_SUPERTREND" if f == "supertrend_pullback" else "TIMING_15M_ROC")
        for a, f, v in CASES
    ]
    if [
        (c.asset, c.family, c.architecture, c.execution_policy) for c in protocol.configurations
    ] != expected:
        raise ValueError("Only the three frozen ETH cases are authorized")
    return protocol


def context(repo, protocol, code):
    source = (repo / protocol.source_run).resolve()
    if sha(source / "artifact_manifest.json") != protocol.source_manifest_sha256:
        raise ValueError("Pinned baseline artifact manifest changed")
    verify_artifacts(source)
    phase = read_json(source / "phase.json")
    child = (source / phase["batch"]).resolve()
    if phase["phase"] != "a" or not child.is_relative_to(source):
        raise ValueError("Invalid baseline phase A source")
    if read_json(source / "verification.json")["status"] != "completed":
        raise ValueError("Baseline source is incomplete")
    old = {
        k.replace("\\", "/"): v for k, v in read_json(source / "provenance.json")["files"].items()
    }
    frozen = (
        "new_mtf_strategy.py",
        "new_mtf_features.py",
        "mtf_strategy.py",
        "mtf_features.py",
        "features.py",
        "indicators.py",
        "mtf_execution.py",
        "mtf_clock.py",
        "perpetual_execution.py",
        "risk.py",
        "batch_006_analysis.py",
        "config.py",
        "strategies/mtf_supertrend_pullback.py",
        "strategies/mtf_roc_momentum.py",
    )
    for name in ["src/quant_lab/" + f for f in frozen] + ["configs/profiles/mtf_series.yaml"]:
        if name not in old or sha(repo / name) != old[name]:
            raise ValueError(f"Original strategy/accounting source changed: {name}")
    reference, matched, _ = frozen_protocol(repo)
    data = matched_data(reference, matched)
    early, late, boundary = schedule(data, reference)
    plan = read_json(child / "plan.json")
    if [(n, str(a), str(b)) for n, a, b in early + late] != [tuple(w) for w in plan["windows"]]:
        raise ValueError("Historical windows changed")
    if len(early + late) != 56:
        raise ValueError("Expected 5 global windows, 22 folds and 29 segments")
    table = pd.read_csv(child / "results.csv")
    selected = table.loc[
        [
            tuple(r) in CASES
            for r in table[["asset", "family", "architecture"]].itertuples(index=False, name=None)
        ]
    ]
    keys = ["asset", "family", "architecture", "partition", "costs"]
    if len(selected) != 504 or selected.duplicated(keys).any():
        raise ValueError("Baseline reference must contain exactly 504 unique executions")
    references = {tuple(row[k] for k in keys): row for row in selected.to_dict("records")}
    return data, early, late, boundary, reference, child, references


def measure(result, sides, start, end, variant, funding):
    values = metrics(
        result, sides, {"summary": {s: {"mfe_mae_ratio": None} for s in ("long", "short")}}, funding
    )
    values.pop("long_mfe_mae")
    values.pop("short_mfe_mae")
    values["average_holding_hours"] = (
        values["average_holding_bars"] * (0.25 if variant == "timing" else 1)
        if values["average_holding_bars"] is not None
        else None
    )
    values["total_costs"] = values["total_execution_costs"] + values["funding_cost"]
    values["average_trade"] = values["expectancy"]
    return values, {
        "time_in_market_pct": 100 * float(sides.iloc[1:].ne(0).mean()),
        "trades_per_month": len(result.trades) / ((end - start).total_seconds() / 86400 / 30.4375),
        "turnover": result.turnover,
    }


def assert_numerical(actual, expected, path="baseline"):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ValueError(f"Baseline reproduction mismatch: {path} keys")
        for key in expected:
            assert_numerical(actual[key], expected[key], path + "." + key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError(f"Baseline reproduction mismatch: {path} count")
        for i, (a, b) in enumerate(zip(actual, expected, strict=True)):
            assert_numerical(a, b, f"{path}[{i}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if actual is None or not np.isclose(actual, expected, rtol=1e-9, atol=1e-8):
            raise ValueError(f"Baseline reproduction mismatch: {path}: {actual} != {expected}")
    elif actual != expected:
        raise ValueError(f"Baseline reproduction mismatch: {path}: {actual} != {expected}")


def compare_baseline(child, reference, result, sides, values, events):
    identifier = reference["experiment_id"]
    doc = read_json(child / identifier / "result.json")
    actual = json.loads(
        json.dumps(
            clean_json(
                {
                    "metrics": values,
                    "trades": [asdict(t) for t in result.trades],
                    "funding_events": events,
                    "rejections": [asdict(r) for r in result.rejections],
                }
            ),
            default=str,
        )
    )
    assert_numerical(actual, {k: doc[k] for k in actual})
    expected = pd.read_parquet(child / "equity" / (identifier + ".parquet"))
    current = pd.DataFrame({"equity": result.equity, "exposure": result.exposure, "side": sides})
    try:
        pd.testing.assert_frame_equal(
            current, expected, check_dtype=False, check_freq=False, rtol=1e-9, atol=1e-8
        )
    except AssertionError as exc:
        raise ValueError(
            f"Baseline reproduction mismatch: equity/exposure/side {identifier}"
        ) from exc
    return {
        "reference_experiment_id": identifier,
        "status": "reproduced",
        "rtol": 1e-9,
        "atol": 1e-8,
    }
