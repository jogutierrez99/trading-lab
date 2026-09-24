"""Frozen identities, translations and chronology; no performance-driven choices."""

import hashlib
import json

import pandas as pd

from quant_lab.config import ResearchConfig
from quant_lab.study_data import HOURS, aggregate_check, audit, digest
from quant_lab.study_features import unsupported

CHOICES = {
    1: ("trend_base", "momentum_base", "meanrev_base"),
    2: ("volmom_c30", "donadx_b40_20", "squeeze_b15", "regmean_a30"),
    3: ("ema_pullback_c50", "mtf_momentum_c72", "atr_breakout_b15", "trend_strength_c7_60"),
    4: (
        "regime_trend_a18",
        "dual_momentum_a7_30",
        "vol_expansion_trend_a50",
        "low_vol_pullback_b40",
    ),
    5: (
        "channel_break_retest_a24",
        "trend_acceleration_a12",
        "rsi_momentum_reset_a40",
        "vol_contraction_expansion_a6",
    ),
}

TRANSLATIONS = {
    "trend_following": (
        "Donchian20 and EMA200: intentional bars. ATR14: bars; trailing3 ATR unchanged."
    ),
    "mean_reversion": (
        "Bollinger20/std2 and RSI14: intentional bars. RSI thresholds30/70 unchanged."
    ),
    "time_series_momentum": "ROC14d:336/84/14 bars. Original extra one-bar lag retained.",
    "vol_momentum": (
        "ROC30d and volatility30d:720/180/30; EMA200: bars. Annualization sqrt(8760/2190/365)."
    ),
    "donchian_adx": "Donchian40, EMA200 and ADX14: intentional bars. ADX threshold20 unchanged.",
    "bb_squeeze": (
        "BB20/std2 and EMA200: bars. Prior quantile30d and recent squeeze24h:720/180/30 and24/6/1."
    ),
    "regime_meanrev": (
        "BB20/std2, EMA200, RSI14 and ADX14: bars. RSI30, ADX20, distance5% unchanged."
    ),
    "ema_pullback": (
        "EMA50/200, pullbackEMA50, RSI14: bars. Previous-bar touch "
        "retained; time stop120h:120/30/5."
    ),
    "mtf_momentum": (
        "Fixed completed4h EMA50/200 and ROC30d; entry channel72h. Only1h "
        "supported: higher-frame hypothesis otherwise changes."
    ),
    "atr_breakout": (
        "EMA50/200 and ATR14: bars. Quantile30d:720/180/30. Prior-bar ATR/close and K1.5 unchanged."
    ),
    "trend_strength": (
        "EMA50/200: bars. ROC7d/60d, slope24h and channel48h:168/42/7,1440/360/60,24/6/1,48/12/2."
    ),
    "regime_trend": (
        "EMA50/200, ADX14, ATR14: bars. ROC30d, quantile30d, channel48h. Threshold18 unchanged."
    ),
    "dual_momentum": (
        "EMA200: bars. ROC7d/30d:168/42/7 and720/180/30. Raw ROC comparison unchanged."
    ),
    "vol_expansion_trend": (
        "EMA50/200 and ATR14: bars. ROC7d, quantile30d, ATR-ratio mean24h and channel24h."
    ),
    "low_vol_pullback": (
        "EMA20/50/200, RSI14, ATR14: bars; previous-bar touch. "
        "Quantiles30d. Time stop120h:120/30/5."
    ),
    "channel_break_retest": (
        "EMA50/200, ATR14: bars. Channel24h:24/6/1. Explicit retest24 "
        "CANDLES retained. Time stop168h:168/42/7."
    ),
    "trend_acceleration": (
        "EMA50/200: bars. Slope12h, slope72h, acceleration lag24h and "
        "channel24h. Time stop240h. Daily12h unrepresentable: skipped."
    ),
    "rsi_momentum_reset": (
        "EMA50/200, RSI14, ATR14: bars. ROC30d; reset expiry48h:48/12/2. "
        "Crossings remain consecutive candles."
    ),
    "vol_contraction_expansion": (
        "EMA50/200 and ATR14: bars. ROC7d, prior quantiles30d, channel24h."
        " Explicit count>=6 of previous24 CANDLES retained."
    ),
}


def frozen_configs(repo):
    result = []
    for batch, choices in CHOICES.items():
        folders = sorted((repo / "results" / f"batch_{batch:03}").glob("*/metrics.csv"))
        if len(folders) != 1:
            raise ValueError("Ambiguous immutable source batch")
        folder = folders[0].parent
        index = pd.read_csv(
            folders[0], usecols=["candidate", "partition", "costs", "experiment_id"]
        )
        for choice in choices:
            row = index[
                (index.candidate == choice) & (index.partition == "train") & (index.costs == "base")
            ].iloc[0]
            source = folder / row.experiment_id / "result.json"
            doc = json.loads(source.read_text(encoding="utf-8"))
            research = ResearchConfig.model_validate_json(json.dumps(doc["research_config"]))
            config = next(s for s in research.strategies if s.enabled)
            result.append(
                {
                    "candidate": choice,
                    "config": config.model_dump(mode="json"),
                    "source": str(source.relative_to(repo)),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            )
    if len({r["config"]["name"] for r in result}) != 19:
        raise ValueError("Expected exactly19 frozen strategy identities")
    return result


def datasets(repo):
    frames, audits, manifests = {}, {}, {}
    for asset in ("BTCUSDT", "ETHUSDT"):
        for tf in HOURS:
            candidates = list(
                (repo / "data/cross_market_timeframe_study_001" / asset / tf).glob(
                    "*/manifest.json"
                )
            )
            path = max(candidates, key=lambda p: json.loads(p.read_text())["audit"]["rows"])
            manifest = json.loads(path.read_text(encoding="utf-8"))
            parquet = path.parent / "candles.parquet"
            if hashlib.sha256(parquet.read_bytes()).hexdigest() != manifest["parquet_sha256"]:
                raise ValueError("Parquet integrity failed")
            frame = pd.read_parquet(parquet)
            quality = audit(frame, asset, tf, manifest["audit"]["start"], manifest["audit"]["end"])
            if quality["status"] == "INVALID" or quality["hash"] != manifest["audit"]["hash"]:
                raise ValueError("Dataset audit failed")
            key = f"{asset}/{tf}"
            frames[key], audits[key] = frame, quality
            manifests[key] = {
                "path": str(path.relative_to(repo)),
                "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    checks = {
        f"{a}/{tf}": aggregate_check(frames[f"{a}/1h"], frames[f"{a}/{tf}"], tf)
        for a in ("BTCUSDT", "ETHUSDT")
        for tf in ("4h", "1d")
    }
    common = None
    for key, frame in frames.items():
        count = frame.groupby(frame.index.floor("D")).size()
        good = count.index[count == 24 // HOURS[key.split("/")[1]]]
        common = good if common is None else common.intersection(good)
    rejected = pd.DatetimeIndex(
        sorted({pd.Timestamp(d) for c in checks.values() for d in c["mismatch_days"]})
    )
    common = common.difference(rejected)
    if len(common) < 730:
        raise ValueError("Fewer than730 comparable days")
    clean = {k: f.loc[f.index.floor("D").isin(common)] for k, f in frames.items()}
    post = {
        f"{a}/{tf}": aggregate_check(clean[f"{a}/1h"], clean[f"{a}/{tf}"], tf)
        for a in ("BTCUSDT", "ETHUSDT")
        for tf in ("4h", "1d")
    }
    if any(c["status"] != "PASS" for c in post.values()):
        raise ValueError("Aggregation still fails after explicit quarantine")
    return clean, {
        "raw": audits,
        "manifests": manifests,
        "aggregation_raw": checks,
        "aggregation_comparable": post,
        "excluded_discrepancy_days": list(map(str, rejected)),
        "common_days": len(common),
        "common_hashes": {k: digest(f, *k.split("/")) for k, f in clean.items()},
        "common_policy": (
            "Intersect complete UTC days across all six datasets; remove every"
            " mismatch day from all six; no interpolation."
        ),
    }


def windows(start, end):
    days = (end - start).days
    bounds = [start + pd.Timedelta(days=int(days * q)) for q in (0, 0.5, 0.7, 0.85, 1)]
    if any(b <= a for a, b in zip(bounds, bounds[1:], strict=False)):
        raise ValueError("Insufficient chronological history")
    return [
        (name, a, b)
        for name, a, b in zip(
            ("train", "validation", "test", "final_holdout"), bounds, bounds[1:], strict=False
        )
    ]


def translation_document(configs):
    lines = [
        "# Frozen timeframe translations",
        "",
        "Adapter v1. No parameter search. Original configs and signal predicates preserved.",
        "All risk ATR periods remain bars; ATR multiples/percentages unchanged.",
        "One-bar lags/crossings refer to consecutive candles, not one elapsed hour.",
        "Quantile720 is interpreted as a30-day empirical distribution; probabilities unchanged.",
        "This is an explicit temporal interpretation, not a claim of identical signals.",
        "Features reset after excluded days; no position crosses a gap or partition.",
        "",
        "| Strategy | Translation |",
        "|---|---|",
    ]
    lines += [f"| {r['config']['name']} | {TRANSLATIONS[r['config']['name']]} |" for r in configs]
    lines += [
        "",
        (
            "Versions1.0.0. 108 evaluable combinations;6 skips: MTF4h/1d and "
            "acceleration1d, both assets."
        ),
        (
            "Warmup uses preceding candles within the same continuous segment."
            " Initial segment starts cold; incomplete indicators cannot emit "
            "entries."
        ),
        (
            "Holdout follows train/validation/test for ALL combinations. "
            "Full/annual diagnostics follow unlock. No selection stage exists."
        ),
    ]
    return "\n".join(lines) + "\n"


def matrix(configs):
    return [
        {
            "strategy": r["config"]["name"],
            "candidate": r["candidate"],
            "asset": a,
            "timeframe": tf,
            "reason": unsupported(r["config"]["name"], tf),
        }
        for r in configs
        for a in ("BTCUSDT", "ETHUSDT")
        for tf in HOURS
    ]
