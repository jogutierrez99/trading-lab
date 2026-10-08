"""Frozen historical regions, descriptive evidence and small synthetic audited runs."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from test_lab import lab as lab_fixture
from test_lab_research_workflow import fingerprint

from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle
from quant_lab.lab_challenge import prepare_challenge, resolve_challenge, run_challenge
from quant_lab.lab_eth_short_history import (
    EXPERIMENTS,
    EXPORTS,
    FAMILIES,
    LOCK,
    WARNING,
    check_lock,
    costs_comparison,
    neighbors,
    previous_sources,
    publish,
    report,
    run_one,
    scorecard,
    strategy_comparison,
    validate,
)
from quant_lab.lab_evidence import sha256
from quant_lab.lab_trend_expansion import main

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sources(tmp_path):
    root, _, _, frame = lab_fixture.__wrapped__(tmp_path)
    request = HistoryRequest(
        symbol="ETH/USDT",
        start=datetime(2022, 1, 2, tzinfo=UTC),
        end=datetime(2022, 1, 18, tzinfo=UTC),
        warmup_bars=24,
    )
    bundle = save_bundle(root / "data", frame, request, [])
    lock = yaml.safe_load((ROOT / LOCK).read_text())
    old = previous_sources(ROOT, lock)
    publication = root / lock["previous_publication"]
    publication.mkdir(parents=True)
    (root / "configs/challenges").mkdir()
    specs, sources, hashes = [], [], {}
    for family, name in zip(FAMILIES, EXPERIMENTS, strict=True):
        source = copy.deepcopy(old[family])
        path = root / "configs/challenges" / (name + ".yaml")
        raw = yaml.safe_load((ROOT / "configs/challenges" / path.name).read_text())
        raw["markets"][0].update(
            dataset="../../data/" + bundle.name, dataset_id=bundle.name, warmup_bars=250
        )
        profile = root / "configs" / (family + ".yaml")
        config = source["resolved_strategy"]
        config["parameters"].update(trend_length=10, slope_lookback=2, atr_length=3, exit_length=3)
        if "fast_length" in config["parameters"]:
            config["parameters"]["fast_length"] = 3
        if "breakout_length" in config["parameters"]:
            config["parameters"]["breakout_length"] = 3
        for candidate in raw["candidates"]:
            candidate["parameters"].update(
                {
                    k: config["parameters"][k]
                    for k in ("trend_length", "slope_lookback", "atr_length", "exit_length")
                }
            )
            if "fast_length" in candidate["parameters"]:
                candidate["parameters"]["fast_length"] = 3
        profile.write_text(yaml.safe_dump(config), encoding="utf-8")
        raw["strategy"]["config"] = "../" + profile.name
        start = datetime(2022, 1, 1, tzinfo=UTC)
        boundaries = [
            start + timedelta(hours=250),
            datetime(2022, 1, 13, tzinfo=UTC),
            datetime(2022, 1, 15, tzinfo=UTC),
            datetime(2022, 1, 17, tzinfo=UTC),
        ]
        # Three compressed synthetic periods exercise year labels, not economic history.
        raw["historical_challenge"].update(
            requested=dict(start=start, end=boundaries[-1]),
            warmup_start=start,
            segments=[
                dict(label=f"year_{year}", start=boundaries[i], end=boundaries[i + 1])
                for i, year in enumerate((2020, 2021, 2022))
            ],
        )
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        file, spec = resolve_challenge(root, name)
        context = prepare_challenge(file, spec)
        source["parameters"] = [c["parameters"] for c in context["candidates"]]
        source["parameter_risks"] = [c["risk"] for c in context["candidates"]]
        source["resolved_strategy"] = context["template"].model_dump(mode="json")
        source["app"] = context["app"].model_dump(mode="json")
        source["original_plan"]["markets"] = [spec.markets[0].model_dump(mode="json")]
        sources.append(source)
        specs.append((file, spec))
        for p in (file, profile):
            hashes[p.relative_to(root).as_posix()] = sha256(p)
    (publication / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    pd.DataFrame(
        [
            dict(
                family=f,
                period="test",
                scenario=s,
                median_return_pct=1.0,
                median_profit_factor=1.1,
                median_expectancy=1.0,
            )
            for f in FAMILIES
            for s in ("base", "adverse")
        ]
    ).to_csv(publication / "strategy_comparison.csv", index=False)
    for p in publication.iterdir():
        hashes[p.relative_to(root).as_posix()] = sha256(p)
    lock["file_sha256"] = hashes
    (root / LOCK).parent.mkdir(parents=True)
    (root / LOCK).write_text(yaml.safe_dump(lock), encoding="utf-8")
    return root, [run_challenge(p, s, root) for p, s in specs]


def test_repository_freeze_source_regions_and_periods():
    lock = check_lock(ROOT)
    previous = previous_sources(ROOT, lock)
    for family, name in zip(FAMILIES, EXPERIMENTS, strict=True):
        _, spec = resolve_challenge(ROOT, name)
        assert [c.parameters for c in spec.candidates] == previous[family]["parameters"]
        assert len(spec.candidates) == 6 and spec.modes == ["SHORT_ONLY"]
        periods = spec.historical_challenge.segments
        assert periods[0].start == datetime(2020, 2, 11, 16, tzinfo=UTC)
        assert periods[-1].end == datetime(2023, 1, 1, tzinfo=UTC)
        assert [p.label for p in periods] == ["year_2020", "year_2021", "year_2022"]
        assert not spec.validation.walk_forward
        assert spec.markets[0].warmup_bars == 1000
    assert sha256(ROOT / "src/quant_lab/lab_cli.py") == (
        "a9bd82660446cea7a176110ffe73baac6c00bac25437eb921b68ae0fb60368f7"
    )


def test_synthetic_report_publish_and_sources_immutable(sources, monkeypatch):
    root, runs = sources
    before = [fingerprint(p) for p in runs]
    monkeypatch.setattr("quant_lab.lab_challenge.evaluate", lambda *a: pytest.fail("No simulation"))
    assert validate(root, full=True)["backtests_executed"] == 0
    directory = report(root, [p.name for p in runs])
    frame = pd.read_csv(directory / "summary.csv")
    assert frame["mode"].eq("SHORT_ONLY").all() and frame.symbol.eq("ETHUSDT").all()
    assert set(frame.year) == {2020, 2021, 2022}
    assert frame.long_contribution.eq(0).all()
    assert (
        frame.total_modeled_costs.notna().all() and frame.average_close_exposure_pct.notna().all()
    )
    assert len(pd.read_csv(directory / "regime_comparison.csv")) == 19 * len(frame)
    assert len(pd.read_csv(directory / "outlier_dependency.csv")) == 4 * len(frame)
    assert WARNING in (directory / "conclusions.md").read_text()
    result = publish(root, directory.name)
    destination = Path(result["publication_directory"])
    assert set(result["published"]) == set(EXPORTS) | {"metadata.json"}
    assert not list(destination.glob("*.parquet"))
    assert str(root) not in (destination / "sources.json").read_text()
    assert before == [fingerprint(p) for p in runs]
    assert main(["--root", str(root), "eth-short-history", "validate"]) == 0
    with pytest.raises(FileExistsError):
        publish(root, directory.name)
    with pytest.raises(ValueError, match="file limit"):
        publish(root, directory.name, max_bytes=1)
    (directory / "summary.csv").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        publish(root, directory.name)


def test_reject_changed_previous_publication_and_wrong_order(sources):
    root, runs = sources
    with pytest.raises(ValueError, match="order"):
        report(root, [p.name for p in reversed(runs)])
    lock = check_lock(root)
    file = root / lock["previous_publication"] / "sources.json"
    file.write_text(file.read_text() + "\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate(root)


def test_run_preflight_does_not_simulate_in_test(sources, monkeypatch):
    root, _ = sources
    calls = []
    monkeypatch.setattr(
        "quant_lab.lab_eth_short_history.run_challenge",
        lambda p, s, r: calls.append(s.experiment_id) or p,
    )
    run_one(root, EXPERIMENTS[0])
    assert calls == [EXPERIMENTS[0]]
    calls.clear()
    path = root / "configs/challenges" / (EXPERIMENTS[1] + ".yaml")
    path.write_text(path.read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        run_one(root, EXPERIMENTS[0])
    assert not calls


def test_descriptive_denominators_neighbors_and_cost_flags():
    rows = []
    for family in FAMILIES:
        for period, year in (
            ("HISTORICAL_CHALLENGE/year_2020", 2020),
            ("HISTORICAL_CHALLENGE/year_2021", 2021),
        ):
            for scenario in ("base", "adverse"):
                for value in (30, 40, 50):
                    r = 1.0 if scenario == "base" else -1.0
                    rows.append(
                        dict(
                            family=family,
                            year=year,
                            period=period,
                            scenario=scenario,
                            symbol="ETHUSDT",
                            timeframe="1h",
                            mode="SHORT_ONLY",
                            configuration_id=str(value),
                            experiment_id=family,
                            run_id=family,
                            backtest_id=family + str(value) + scenario,
                            parameters=json.dumps(dict(length=value)),
                            return_pct=r,
                            profit_factor=1.1 if value != 50 else np.nan,
                            expectancy=r,
                            max_drawdown_pct=2.0,
                            sharpe=r,
                            sortino=r,
                            closed_trades=30,
                            total_modeled_costs=1.0,
                            average_close_exposure_pct=5.0,
                        )
                    )
    frame = pd.DataFrame(rows)
    card = scorecard(frame)
    assert card.query('scenario=="base"').positive_configs_pct.eq(100).all()
    assert card.pf_above_one_pct.eq(200 / 3).all() and card.undefined_pf_configs.eq(1).all()
    assert card.verdict.isna().all()  # No economic score/automatic survivor.
    assert len(neighbors(frame)) == 16
    assert len(strategy_comparison(card)) == 4
    cost = costs_comparison(frame)
    assert cost.return_pct_delta.eq(-2.0).all()
    assert cost.edge_disappears_adverse.dropna().all()
    assert cost.edge_disappears_adverse.isna().sum() == 4
