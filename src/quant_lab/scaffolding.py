"""Generate a strategy, configuration and test without overwriting existing files."""

import argparse
import keyword
import re
from datetime import UTC, datetime
from pathlib import Path


def create_strategy(name: str, root: Path) -> tuple[Path, ...]:
    if (
        not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", name)
        or keyword.iskeyword(name)
        or name in {"base", "registry", "con", "prn", "aux", "nul"}
        or re.fullmatch(r"(?:com|lpt)[1-9]", name)
    ):
        raise ValueError("Use a non-reserved lowercase snake_case strategy name")
    root = root.resolve()
    if not (root / "src/quant_lab/strategies/base.py").is_file():
        raise ValueError(f"Not a quant-trading-lab source checkout: {root}")
    class_name = "".join(word.capitalize() for word in name.split("_")) + "Strategy"
    module = f'''"""Research scaffold: implement deterministic rules before enabling."""

from quant_lab.config import StrictModel
from quant_lab.strategies.base import BaseStrategy, FeatureFrame


class Parameters(StrictModel):
    """Declare and constrain every strategy-specific parameter here."""


class {class_name}(BaseStrategy[Parameters]):
    name = "{name}"
    version = "1.0.0"
    description = "Implement and describe the research hypothesis"
    status = "experimental"
    created_at = "{datetime.now(UTC).isoformat()}"
    lab_timeframes = ("1h",)
    lab_modes = ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT")
    parameter_model = Parameters

    def prepare_features(self, candles: FeatureFrame) -> FeatureFrame:
        raise NotImplementedError("Implement causal features before enabling this strategy")

    def generate_long_entries(self, features: FeatureFrame) -> list[bool]:
        raise NotImplementedError("Implement long entry rules")

    def generate_long_exits(self, features: FeatureFrame) -> list[bool]:
        raise NotImplementedError("Implement long exit rules")

    def generate_short_entries(self, features: FeatureFrame) -> list[bool]:
        raise NotImplementedError("Implement short entry rules")

    def generate_short_exits(self, features: FeatureFrame) -> list[bool]:
        raise NotImplementedError("Implement short exit rules")
'''
    config = f"""# Scaffold only; implement rules and behavioral tests before enabling.
name: {name}
version: 1.0.0
enabled: false
market:
  provider: binance
  symbol: BTC/USDT
  timeframe: 1h
parameters: {{}}
"""
    test = f'''"""Replace scaffold checks with rule and prefix-invariance tests when implemented."""

import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.{name} import {class_name}
from quant_lab.strategies.registry import StrategyRegistry


def test_{name}_scaffold():
    registry = StrategyRegistry().discover()
    assert "{name}" in registry.names()
    config = StrategyConfig(name="{name}", enabled=True)
    strategy = registry.create(config)
    assert isinstance(strategy, {class_name})
    assert strategy.metadata()["version"] == "1.0.0"
    with pytest.raises(NotImplementedError):
        strategy.generate_signals([])
'''
    files = {
        root / f"src/quant_lab/strategies/{name}.py": module,
        root / f"configs/strategies/{name}.yaml": config,
        root / f"tests/unit/test_{name}.py": test,
    }
    for path in files:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    created = []
    try:
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                created.append(path)
                stream.write(content)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return tuple(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Source checkout root")
    args = parser.parse_args()
    try:
        paths = create_strategy(args.name, args.root)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
