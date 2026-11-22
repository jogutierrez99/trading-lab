"""Host evidence for a deliberately narrow, statically inspected OHLCV protocol.

No engine import/execution. This inventory describes capabilities, not dataset
availability or permission. Synthetic dataset bytes must be supplied separately.
"""

from pathlib import Path

from trading_lab_catalog.verification import sha
from trading_lab_orchestration.contracts import canonical

from .context import ResearchError
from .models import identity

SOURCE_REVISION = "0a713557ae19ee549a39bfbc46aa6472ee2bbd2e"
# SHA-256 of inspected Git contents with LF newlines, independent of checkout EOL.
SOURCES = {
    "src/quant_lab/config.py": "2e66b3c2574f903305fd35bb86ddcf5d10ac5b943ca38623b21f485d6e04026a",
    "src/quant_lab/lab_runner.py": (
        "8a66db037c6541af839951078af91baf3361c5bde70799e1f90ec6475c557cd4"
    ),
    "src/quant_lab/study_backend.py": (
        "a5533aa5e19edcaab5caf025121829622b839f6e95faba13a00d67a91dd65c5b"
    ),
    "src/quant_lab/backtest.py": (
        "42a582117a29c152e8a19597a3522db794faf335acef1fb793e9f527d0388a81"
    ),
    "src/quant_lab/risk.py": "dfcfde6cf79b792dda39eb78ce8a2ba92f8bdb51bfecf5bd3c3e74b8b7fd58be",
    "src/quant_lab/execution_config.py": (
        "aad24e2c7697f23279dabe63959793b9b5497e14a5978777a8c637dbf1cc6b3a"
    ),
    "src/quant_lab/features.py": (
        "396f82a75b4ed7a2a90837dcce9beb23f88d39f2679cfcd5c41acac7153e2392"
    ),
    "src/quant_lab/study_data.py": (
        "991fecf392a796050a33b3c854bd3b8387e4c45003a26137648eb25ded5e6446"
    ),
    "docs/lab-workflow.md": "742ff08c3fc58e96acb0443d4834be3f3ea4d1cd47a2c465fe2193b962e00bf6",
}
PROTOCOL = {
    "reference_id": "ohlcv_design_subset_v1",
    "version": "1.0",
    "runner": "ordinary_lab_ohlcv",
    "backend": "StudyBackend.v1",
    "market_modes": ["spot", "synthetic"],
    "timeframes": ["1h", "4h", "1d"],
    "directions": {"spot": ["LONG_ONLY"], "synthetic": ["LONG_ONLY", "SHORT_ONLY"]},
    "signal_availability": "CANDLE_CLOSE",
    "entry_timing": "NEXT_OPEN",
    "backend_sizing_methods": ["stop_risk", "fixed_notional", "volatility_target"],
    "sizing_methods": ["stop_risk"],
    "sizing_limitations": (
        "Prepared designs require stop_risk to enforce RiskConstraints.risk_per_trade_pct; "
        "fixed_notional and volatility sizing require another reviewed risk mapping"
    ),
    "stops": ["ATR"],
    "targets": ["RISK_REWARD"],
    "cost_application": "BOTH_SIDES_FEE_ADVERSE_SLIPPAGE_HALF_SPREAD",
    "intrabar": "ADVERSE_OPEN_GAP_THEN_STOP_BEFORE_TARGET",
    "capital_policy": "RESET_PER_SEGMENT",
    "funding": {"spot": "NOT_APPLICABLE", "synthetic": "NOT_MODELLED"},
    "perpetual": "UNSUPPORTED_IN_THIS_INVENTORY_REQUIRES_DEDICATED_VERIFIED_ADAPTER",
    "multi_timeframe": "UNSUPPORTED_IN_THIS_DESIGN_SUBSET",
    "gap_policy": "REJECT_DISCONTINUITIES",
    "max_open_positions": 1,
    "execution_filters": {
        "quantity_step": 0.001,
        "min_quantity": 0.001,
        "min_notional": 10.0,
        "filter_assumption": "SYNTHETIC_FILTERS_NOT_VENUE_RULES",
        "rounding": "ROUND_FLOOR",
        "liquidate_at_end": True,
    },
    "formula_operators": {
        "PRICE": "input[T-shift]; window=1",
        "SMA": "Arithmetic mean of input[T-shift-window+1:T-shift+1], min_periods=window",
        "ROLLING_MAX": "Maximum input[T-shift-window+1:T-shift+1], min_periods=window",
        "ROLLING_MIN": "Minimum input[T-shift-window+1:T-shift+1], min_periods=window",
        "ATR_SMA": (
            "TR[t]=max(high[t]-low[t],abs(high[t]-close[t-1]),abs(low[t]-close[t-1])); "
            "missing previous close makes TR NaN; arithmetic mean of last window TR ending "
            "T-shift, min_periods=window; additional previous candle required"
        ),
    },
    "protective_levels": (
        "distance=unshifted ATR_SMA at signal close * stop.multiple; "
        "entry=next open with adverse costs; stop=entry-side*distance; "
        "target=entry+side*distance*target.multiple; no pyramiding/same-open reversal"
    ),
    "sizing_rules": (
        "stop_risk: budget=equity*risk_per_trade_pct/100; quantity bounded by "
        "cost-inclusive expected stop loss and equity*min(max_position_pct,max_exposure_pct)/100; "
        "fixed_notional also caps by position_pct; fees included in capital cap; "
        "ROUND_FLOOR to quantity_step; reject below min_quantity/min_notional"
    ),
    "limitations": [
        "Static capability inspection, not an execution or fill-equivalence test",
        "Subset only: no trailing, HTF, structural levels or volatility sizing in Designer V1",
        "Synthetic data availability is separate from real market coverage",
    ],
}


class DesignCapabilities:
    """Trusted host fixture. It cannot be minted by a provider JSON response.

    Not a security boundary against a malicious Python host. Real adapters and
    production data admission require a later independently authorized boundary.
    """

    def __init__(
        self,
        repository: Path,
        *,
        dataset_id: str,
        dataset_bytes: bytes | None,
        asset: str,
        market_type: str,
        timeframe: str,
        coverage_start_utc: str,
        coverage_end_utc: str,
    ):
        from pydantic import TypeAdapter

        from .models import ID, Market

        TypeAdapter(ID).validate_python(dataset_id, strict=True)
        market = Market(
            asset=asset,
            market_type=market_type,
            timeframe=timeframe,
            requested_years=None,
            coverage_start_utc=coverage_start_utc,
            coverage_end_utc=coverage_end_utc,
        )
        if dataset_bytes is not None and (
            type(dataset_bytes) is not bytes or not 1 <= len(dataset_bytes) <= 64 * 1024
        ):
            raise ValueError("Bounded synthetic dataset bytes required")
        observed = {}
        for name, expected in SOURCES.items():
            observed[name] = sha((Path(repository) / name).read_bytes().replace(b"\r\n", b"\n"))
            if observed[name] != expected:
                raise ResearchError("CAPABILITY_SOURCE_CHANGED")
        payload = {
            "mode": "SYNTHETIC_HOST_FIXTURE_ONLY",
            "source_revision": SOURCE_REVISION,
            "source_hashes_lf": observed,
            "protocol": PROTOCOL,
            "protocol_sha256": sha(canonical(PROTOCOL).encode()),
            "dataset": {
                "reference_id": dataset_id,
                "sha256": sha(dataset_bytes) if dataset_bytes is not None else None,
                "availability": "MANUALLY_VERIFIED" if dataset_bytes is not None else "PENDING",
                "market": market.model_dump(mode="json"),
                "scope": "SYNTHETIC_BYTES_NOT_REAL_MARKET_VALIDATION",
            },
        }
        self._bytes = canonical(payload).encode()
        self.fingerprint = identity("DesignCapabilities", payload)

    def payload(self) -> dict:
        from trading_lab_catalog.verification import parse

        return parse(self._bytes)
