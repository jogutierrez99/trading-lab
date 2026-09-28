"""Validated linear base-denominated X-Perp contract arithmetic using Decimal."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal


def positive(value):
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("Expected a finite positive instrument/size value")
    return result


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    base: str
    contract_size: Decimal
    lot_size: Decimal
    min_size: Decimal
    tick_size: Decimal
    max_leverage: Decimal
    settlement_currency: str = "USDC"

    @classmethod
    def parse(cls, row):
        base = row["instId"].split("-")[0]
        expected = {
            "instType": "FUTURES",
            "ruleType": "xperp",
            "ctType": "linear",
            "state": "live",
            "ctValCcy": base,
        }
        if any(row.get(k) != v for k, v in expected.items()):
            raise ValueError("Unsupported or inactive OKX EU linear base-denominated X-Perp")
        if row.get("settleCcy") not in {"USD", "USDC"}:
            raise ValueError("Unsupported X-Perp settlement currency")
        return cls(
            row["instId"],
            base,
            *[positive(row[k]) for k in ("ctVal", "lotSz", "minSz", "tickSz", "lever")],
            settlement_currency=row["settleCcy"],
        )

    def round_price(self, price, *, upward=False):
        value = positive(price)
        rounding = ROUND_CEILING if upward else ROUND_FLOOR
        return (value / self.tick_size).to_integral_value(rounding=rounding) * self.tick_size

    def convert(self, price, *, target_quantity=None, target_notional=None, leverage=1):
        price, leverage = positive(price), positive(leverage)
        if leverage > self.max_leverage or leverage > 1:
            raise ValueError("Forward phase permits at most 1x theoretical leverage")
        if (target_quantity is None) == (target_notional is None):
            raise ValueError("Specify exactly one target quantity or target notional")
        quantity = (
            positive(target_quantity)
            if target_quantity is not None
            else positive(target_notional) / price
        )
        requested = quantity / self.contract_size
        rounded = (requested / self.lot_size).to_integral_value(
            rounding=ROUND_FLOOR
        ) * self.lot_size
        if rounded < self.min_size or rounded <= 0:
            raise ValueError("below_min_size")
        return {
            "target_notional": str(quantity * price),
            "target_base_quantity": str(quantity),
            "contract_size": str(self.contract_size),
            "contracts_requested": str(requested),
            "contracts_rounded": str(rounded),
            "estimated_notional": str(rounded * self.contract_size * price),
        }
