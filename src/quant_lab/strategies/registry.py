"""Instance-scoped discovery: adding a strategy never requires editing this module."""

import importlib
import inspect
import pkgutil
import re
from datetime import datetime, timedelta

from quant_lab.config import StrategyConfig, StrictModel
from quant_lab.strategies.base import BaseStrategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, type[BaseStrategy]] = {}

    def register(self, strategy: type[BaseStrategy]) -> None:
        if not inspect.isclass(strategy) or not issubclass(strategy, BaseStrategy):
            raise TypeError("Strategy must subclass BaseStrategy")
        if inspect.isabstract(strategy):
            raise TypeError("Cannot register an abstract strategy")
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", getattr(strategy, "name", "")):
            raise ValueError("Strategy must declare a valid name")
        if not re.fullmatch(r"\d+\.\d+\.\d+", strategy.version):
            raise ValueError("Strategy version must be MAJOR.MINOR.PATCH")
        if strategy.status not in {
            "experimental",
            "research",
            "promising",
            "validated",
            "rejected",
            "deprecated",
        }:
            raise ValueError("Invalid strategy status metadata")
        if strategy.created_at is not None:
            if datetime.fromisoformat(strategy.created_at).utcoffset() != timedelta(0):
                raise ValueError("Strategy created_at must be timezone-aware UTC")
        model = getattr(strategy, "parameter_model", None)
        if not inspect.isclass(model) or not issubclass(model, StrictModel):
            raise TypeError("Strategy must declare a StrictModel parameter_model")
        if strategy.name in self._strategies:
            raise ValueError(f"Strategy already registered: {strategy.name}")
        self._strategies[strategy.name] = strategy

    def discover(self, package_name: str = "quant_lab.strategies") -> "StrategyRegistry":
        """Import trusted local modules only. Fail atomically on duplicate/invalid plugins."""
        package = importlib.import_module(package_name)
        importlib.invalidate_caches()
        candidate = StrategyRegistry()
        candidate._strategies = self._strategies.copy()
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
            if info.name.startswith("_") or info.name in {"base", "registry"}:
                continue
            module = importlib.import_module(f"{package_name}.{info.name}")
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ == module.__name__ and issubclass(cls, BaseStrategy):
                    if candidate._strategies.get(getattr(cls, "name", None)) is cls:
                        continue
                    candidate.register(cls)
        self._strategies = candidate._strategies
        return self

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))

    def implementation(self, name: str) -> type[BaseStrategy]:
        try:
            return self._strategies[name]
        except KeyError as exc:
            raise ValueError(f"Unknown strategy: {name}") from exc

    def catalogue(self) -> list[dict]:
        return [
            {
                "strategy_id": name,
                "version": cls.version,
                "description": cls.description or inspect.getmodule(cls).__doc__ or name,
                "implementation": f"{cls.__module__}.{cls.__name__}",
                "config": f"configs/strategies/{name}.yaml",
                "status": cls.status,
                "created_at": cls.created_at,
                "timeframes": cls.lab_timeframes,
                "modes": cls.lab_modes,
                "execution": cls.lab_execution,
            }
            for name in self.names()
            for cls in [self.implementation(name)]
        ]

    def create(self, config: StrategyConfig) -> BaseStrategy:
        if not config.enabled:
            raise ValueError(f"Strategy is disabled: {config.name}")
        try:
            cls = self._strategies[config.name]
        except KeyError as exc:
            raise ValueError(f"Unknown strategy: {config.name}") from exc
        return cls(config)
