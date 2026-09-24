from quant_lab.config import StrategyConfig


def test_prefix_invariance_pattern(example_class):
    """Template for every future real strategy; this alone does not prove engine causality."""
    strategy = example_class(StrategyConfig(name="example"))
    history = [9, 11, 8, 12, 10]
    full = strategy.generate_signals(history)
    for end in range(1, len(history) + 1):
        prefix = strategy.generate_signals(history[:end])
        for field in ("long_entries", "long_exits", "short_entries", "short_exits"):
            assert getattr(prefix, field) == getattr(full, field)[:end]
