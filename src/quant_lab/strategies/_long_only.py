"""Abstract helper for explicitly long-only research modules."""

from quant_lab.strategies.base import BaseStrategy


class LongOnlyStrategy(BaseStrategy):
    lab_modes = ("LONG_ONLY",)

    def generate_short_entries(self, features) -> list[bool]:
        return [False] * len(features)

    def generate_short_exits(self, features) -> list[bool]:
        return [False] * len(features)
