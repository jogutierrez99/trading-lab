import copy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from test_trend_rsi_lab import small as small_fixture

from quant_lab.config import load_yaml
from quant_lab.lab_challenge import Challenge, prepare_challenge, run_challenge
from quant_lab.lab_classification import classify
from quant_lab.lab_cli import main
from quant_lab.lab_publish import publish

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "configs/challenges/trend_rsi_pullback_v1_eth_challenge.yaml"


def test_exact_frozen_candidates_and_warmup():
    spec = load_yaml(PATH, Challenge)
    context = prepare_challenge(PATH, spec)
    assert context["backtests"] == 24
    assert len(spec.candidates) == len(context["parameters"]) == 3
    assert [c.mode for c in spec.candidates] == ["LONG_SHORT", "LONG_ONLY", "LONG_ONLY"]
    assert [c.parameters["sma_length"] for c in spec.candidates] == [185, 200, 150]
    assert [c.parameters["rsi_length"] for c in spec.candidates] == [25, 25, 20]
    assert [c.parameters["reward_risk"] for c in spec.candidates] == [1.25, 1.25, 2.0]
    for c in spec.candidates:
        assert (
            c.parameters
            | {
                "variant": "V1",
                "rsi_oversold": 35,
                "rsi_overbought": 65,
                "atr_length": 20,
                "atr_multiplier": 2.5,
                "sma_slope_lookback": 5,
            }
            == c.parameters
        )
    assert len(spec.markets) == 1 and spec.markets[0].symbol == "ETHUSDT"
    assert spec.markets[0].timeframe == "15m"
    assert spec.historical_challenge.requested.start == pd.Timestamp("2020-01-01", tz="UTC")
    assert spec.historical_challenge.segments[0].start == pd.Timestamp("2020-01-11T11:00Z")
    assert spec.historical_challenge.segments[-1].end == pd.Timestamp("2023-06-04", tz="UTC")
    assert all(label.startswith("HISTORICAL_CHALLENGE/") for label, _ in spec.validation.periods())
    assert not hasattr(spec.validation, "test")


def test_challenge_schema_rejects_grid_and_wrong_warmup():
    raw = yaml.safe_load(PATH.read_text())
    with pytest.raises(ValueError, match="Extra inputs"):
        Challenge.model_validate(raw | {"strategy_parameters": {"rsi_oversold": [33, 34]}})
    changed = copy.deepcopy(raw)
    changed["historical_challenge"]["segments"][0]["start"] = changed["historical_challenge"][
        "warmup_start"
    ]
    with pytest.raises(ValueError, match="warmup"):
        Challenge.model_validate(changed)


def test_small_real_backend_challenge_and_publication(tmp_path, monkeypatch):
    root, ordinary, frame = small_fixture.__wrapped__(tmp_path)
    raw = yaml.safe_load(PATH.read_text())
    raw["markets"] = ordinary["markets"]  # Synthetic BTC fixture, production YAML stays ETH.
    raw["historical_challenge"]["warmup_start"] = frame.index[0].to_pydatetime()
    end = frame.index[-1] + pd.Timedelta(minutes=15)
    raw["historical_challenge"]["requested"] = {
        "start": frame.index[0].to_pydatetime(),
        "end": end.to_pydatetime(),
    }
    points = [frame.index[i] for i in (1004, 1100, 1200, 1300)] + [end]
    for i, segment in enumerate(raw["historical_challenge"]["segments"]):
        segment.update(start=points[i].to_pydatetime(), end=points[i + 1].to_pydatetime())
    path = root / "configs/challenges" / PATH.name
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    spec = Challenge.model_validate(raw)
    assert main(["--root", str(root), "challenge", "validate", spec.experiment_id, "--full"]) == 0
    output = run_challenge(path, spec, root)
    rows = pd.read_csv(output / "metrics.csv")
    assert len(rows) == 24 and rows.candidate_id.nunique() == 3
    assert rows.period.str.startswith("HISTORICAL_CHALLENGE/").all()
    assert rows[rows.candidate_id == "candidate_a"]["mode"].eq("LONG_SHORT").all()
    assert rows[rows.candidate_id != "candidate_a"]["mode"].eq("LONG_ONLY").all()
    assert json.loads((output / "outcome.json").read_text())["status"] == "COMPLETE"
    monkeypatch.setattr("quant_lab.lab_challenge.evaluate", lambda *a: pytest.fail("No rerun"))
    result = publish(root, spec.experiment_id)
    metadata = json.loads((Path(result["publication_directory"]) / "metadata.json").read_text())
    assert metadata["validation"] is None
    assert metadata["historical_challenge"]["label"] == "HISTORICAL_CHALLENGE"
    with pytest.raises(ValueError, match="no TRAIN"):
        classify(root, spec.experiment_id, ROOT / "configs/research/lab_classification_v1.yaml")
