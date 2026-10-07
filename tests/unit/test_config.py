import pytest
from pydantic import ValidationError

from quant_lab.config import (
    AppConfig,
    ConfigurationError,
    CostsConfig,
    MarketConfig,
    RiskConfig,
    StrategyConfig,
    load_research_config,
    load_yaml,
)


def test_repository_configuration(repo_root):
    config = load_research_config(repo_root / "configs/app.yaml")
    assert len(config.strategies) == 41
    assert {s.name for s in config.strategies if s.enabled} == {
        "trend_volatility_breakout_v1",
        "volatility_breakout_intraday_v1",
        "range_mean_reversion_v1",
        "donchian_trend_v1",
        "risk_managed_momentum_v1",
        "rsi_momentum_regime_v1",
        "funding_conditional_momentum_v1",
        "atr_volatility_breakout",
        "donchian_trend_breakout",
        "donchian_atr_breakout",
    }
    assert {m.timeframe for m in config.markets.markets} == {"5m", "15m", "1h", "4h", "1d"}
    assert config.app.costs.trading_fee_pct == 0.05
    assert config.model_dump(mode="json") == load_research_config(
        repo_root / "configs/app.yaml"
    ).model_dump(mode="json")


@pytest.mark.parametrize(
    "model,raw",
    [
        (AppConfig, {"mode": "live"}),
        (AppConfig, {"starting_capital": 0}),
        (AppConfig, {"unexpected": True}),
        (CostsConfig, {"slippage_pct": -1.0}),
        (CostsConfig, {"spread_pct": float("nan")}),
        (RiskConfig, {"max_position_pct": 101.0}),
        (RiskConfig, {"max_position_pct": 30.0, "max_exposure_pct": 20.0}),
        (MarketConfig, {"timeframe": "0h"}),
        (StrategyConfig, {"name": "../bad"}),
        (StrategyConfig, {"name": "valid", "enabled": "false"}),
        (StrategyConfig, {"name": "valid", "version": "latest"}),
    ],
)
def test_invalid_configuration(model, raw):
    with pytest.raises(ValidationError):
        model.model_validate(raw)


@pytest.mark.parametrize(
    "text",
    [
        "mode: research\nmode: research\n",
        "[",
        "",
        "- list",
        "!!python/object:evil {}",
        "costs:\n  spread_pct: 1\n  spread_pct: 2\n",
    ],
)
def test_bad_yaml_is_contextual(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(ConfigurationError, match="bad.yaml"):
        load_yaml(path, AppConfig)


def test_risk_inheritance_and_relative_paths(repo_root, tmp_path, monkeypatch):
    import shutil

    shutil.copytree(repo_root / "configs", tmp_path / "configs")
    (tmp_path / "configs/risk.yaml").write_text("risk_per_trade_pct: 0.5\nrisk_reward: 3.0\n")
    monkeypatch.chdir(tmp_path.parent)
    config = load_research_config(tmp_path / "configs/app.yaml")
    sweep = next(s for s in config.strategies if s.name == "liquidity_sweep")
    assert sweep.risk.risk_per_trade_pct == 0.5
    assert sweep.risk.risk_reward == 3.0
    assert sweep.risk.stop_method == "sweep"


def test_missing_directory_fails(tmp_path):
    (tmp_path / "app.yaml").write_text("{}")
    (tmp_path / "risk.yaml").write_text("{}")
    with pytest.raises(ConfigurationError, match="directory"):
        load_research_config(tmp_path / "app.yaml")


def test_risk_is_validated_after_composition(repo_root, tmp_path):
    import shutil

    shutil.copytree(repo_root / "configs", tmp_path / "configs")
    (tmp_path / "configs/risk.yaml").write_text("max_position_pct: 5.0\n")
    path = tmp_path / "configs/strategies/mean_reversion.yaml"
    path.write_text("name: mean_reversion\nrisk:\n  max_exposure_pct: 10.0\n")
    config = load_research_config(tmp_path / "configs/app.yaml")
    strategy = next(s for s in config.strategies if s.name == "mean_reversion")
    assert strategy.risk.max_position_pct == 5.0
    assert strategy.risk.max_exposure_pct == 10.0


def test_duplicate_strategy_names(repo_root, tmp_path):
    import shutil

    shutil.copytree(repo_root / "configs", tmp_path / "configs")
    source = tmp_path / "configs/strategies/mean_reversion.yaml"
    shutil.copyfile(source, source.with_name("duplicate.yaml"))
    with pytest.raises(ConfigurationError, match="Duplicate strategy names"):
        load_research_config(tmp_path / "configs/app.yaml")
