"""Corroborate discrepant mark hours against independent daily public archives."""

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from quant_lab.experiments import write_json
from quant_lab.futures_data import BASE, source_page
from quant_lab.mtf_data import QUARTERS, load_frozen, parse_quarters, quarter_audit


def inspect_asset(asset, item):
    root = QUARTERS / asset / "markPriceKlines"
    source = pd.read_parquet(root / "data.parquet")
    reference = item["mark"]
    fields = ["open", "high", "low", "close"]
    groups = source.resample("h")
    aggregate = groups.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    common = reference.index.intersection(aggregate.index)
    bad = common[
        ~np.isclose(
            aggregate.loc[common, fields], reference.loc[common, fields], rtol=1e-12, atol=1e-8
        ).all(axis=1)
    ]
    missing = reference.index.difference(aggregate.index[groups.size() == 4])
    hours = bad.union(missing)
    patches = []
    checks = []
    for day in hours.floor("D").unique():
        stamp = day.strftime("%Y-%m-%d")
        name = f"{asset}-15m-{stamp}"
        url = f"{BASE}/daily/markPriceKlines/{asset}/15m/{name}.zip"
        try:
            raw, meta = source_page(root / "corroboration", url, name)
            frame = parse_quarters(raw)
            if quarter_audit(frame, asset)["status"] == "INVALID":
                raise ValueError("Invalid daily source")
            for hour in hours[hours.floor("D") == day]:
                subset = frame.loc[hour : hour + pd.Timedelta(minutes=45)]
                ok = len(subset) == 4 and subset.index.equals(
                    pd.date_range(hour, periods=4, freq="15min")
                )
                if ok:
                    values = [
                        subset.open.iloc[0],
                        subset.high.max(),
                        subset.low.min(),
                        subset.close.iloc[-1],
                    ]
                    ok = np.isclose(
                        values, reference.loc[hour, fields], rtol=1e-12, atol=1e-8
                    ).all()
                checks.append({"hour": str(hour), "match": bool(ok), "source": meta})
                if ok:
                    patches.append(subset)
        except (ValueError, RuntimeError, OSError) as exc:
            checks.append({"day": str(day), "error": str(exc)})
    if patches:
        fixed = pd.concat(patches).sort_index()
        fixed.attrs = {}
        fixed.to_parquet(root / "corroborated.parquet")
    write_json(
        root / "corroboration.json",
        {"checks": checks, "repaired_hours": len(patches), "requested_hours": len(hours)},
    )
    print(asset, "repaired", len(patches), "of", len(hours), flush=True)


if __name__ == "__main__":
    data, _ = load_frozen()
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(inspect_asset, a, d) for a, d in data.items()]
        for task in tasks:
            task.result()
