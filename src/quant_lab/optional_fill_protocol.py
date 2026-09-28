"""Strict six-case protocol and pinned, read-only historical/data integrity."""

from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import model_validator

from quant_lab.config import StrictModel, load_yaml
from quant_lab.mtf_series import schedule
from quant_lab.new_mtf_runner import frozen_protocol, matched_data, read_json, sha

DEFAULT_CONFIG = Path("configs/profiles/optional_15m_fill.yaml")
APPROVED = {
    ("ETHUSDT", "ema_adx", "V2"),
    ("ETHUSDT", "roc_momentum", "V2"),
    ("ETHUSDT", "supertrend_pullback", "V2"),
    ("ETHUSDT", "keltner_breakout", "V2"),
    ("BTCUSDT", "supertrend_pullback", "V2"),
    ("ETHUSDT", "trend_pullback", "V1"),
}


class Source(StrictModel):
    path: str
    manifest_sha256: str
    batch: str


class Case(StrictModel):
    asset: str
    family: str
    architecture: str
    source: Literal["new_mtf", "legacy_mtf"]

    @property
    def key(self):
        return self.asset, self.family, self.architecture


class Protocol(StrictModel):
    schema_version: Literal[1]
    execution_policy: Literal["OPTIONAL_15M_FILL"]
    fallback_mode: Literal["causal_deadline_market"]
    window_minutes: Literal[60]
    sources: dict[str, Source]
    configurations: list[Case]

    @model_validator(mode="after")
    def check_matrix(self):
        if len(self.configurations) != 6 or {c.key for c in self.configurations} != APPROVED:
            raise ValueError("Exactly the six selected configurations are required")
        if set(self.sources) != {"new_mtf", "legacy_mtf"}:
            raise ValueError("Both frozen source families are required")
        for c in self.configurations:
            expected = "legacy_mtf" if c.family in {"ema_adx", "trend_pullback"} else "new_mtf"
            if c.source != expected:
                raise ValueError("Configuration/source mismatch")
        return self


def load_protocol(repo, path=DEFAULT_CONFIG):
    return load_yaml(repo / path, Protocol)


def verify_source(repo, source):
    folder = (repo / source.path).resolve()
    if sha(folder / "artifact_manifest.json") != source.manifest_sha256:
        raise ValueError("Source manifest fingerprint changed: " + source.path)
    manifest = read_json(folder / "artifact_manifest.json")
    for name, expected in manifest.items():
        target = (folder / name).resolve()
        if not target.is_relative_to(folder) or sha(target) != expected:
            raise ValueError("Historical artifact changed: " + name)
    if not {"plan.json", "provenance.json", "verification.json"} <= set(manifest):
        raise ValueError("Incomplete source manifest")
    child = (folder / source.batch).resolve()
    if (
        not child.is_relative_to(folder)
        or read_json(child / "verification.json")["status"] != "completed"
    ):
        raise ValueError("Invalid or incomplete source batch")
    return child


def context(repo, protocol):
    sources = {name: verify_source(repo, source) for name, source in protocol.sources.items()}
    reference, matched, _ = frozen_protocol(repo)
    data = matched_data(reference, matched)
    early, late, boundary = schedule(data, reference)
    windows = [(n, str(a), str(b)) for n, a, b in early + late]
    if len(windows) != 56:
        raise ValueError("Expected 56 frozen windows")
    references = {}
    for name, folder in sources.items():
        plan = read_json(folder / "plan.json")
        if windows != [tuple(w) for w in plan["windows"]]:
            raise ValueError("Historical schedule changed")
        table = pd.read_csv(folder / "results.csv")
        for case in [c for c in protocol.configurations if c.source == name]:
            selected = table.loc[
                (table.asset == case.asset)
                & (table.family == case.family)
                & (table.architecture == case.architecture)
                & (table["mode"] == "LONG_ONLY")
                & (table.cohort == "matched")
            ]
            expected = {(w[0], s) for w in windows for s in ("zero", "base", "adverse")}
            if (
                len(selected) != 168
                or set(zip(selected.partition, selected.costs, strict=True)) != expected
            ):
                raise ValueError(f"Missing or duplicate baseline reference: {case.key}")
            references[case.key] = {
                (r["partition"], r["costs"]): r for r in selected.to_dict("records")
            }
    # Freeze original signal and accounting source against the newer source snapshot.
    parent = repo / protocol.sources["new_mtf"].path
    old = {
        k.replace("\\", "/"): v for k, v in read_json(parent / "provenance.json")["files"].items()
    }
    modules = (
        "mtf_strategy",
        "new_mtf_strategy",
        "mtf_features",
        "new_mtf_features",
        "features",
        "indicators",
        "mtf_execution",
        "mtf_clock",
        "perpetual_execution",
        "risk",
        "config",
        "backtest",
        "metrics",
        "batch_006_analysis",
    )
    files = ["src/quant_lab/" + m + ".py" for m in modules]
    files += [
        "src/quant_lab/strategies/mtf_" + f + ".py"
        for f in {c.family for c in protocol.configurations}
    ]
    files += ["configs/profiles/mtf_series.yaml"]
    for path in files:
        if old.get(path) != sha(repo / path):
            raise ValueError("Original strategy/accounting changed: " + path)
    return data, early, late, boundary, reference, sources, references
