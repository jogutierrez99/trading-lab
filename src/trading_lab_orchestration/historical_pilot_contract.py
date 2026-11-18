"""Frozen inputs and bounded transport for the isolated Issue #3 historical pilot."""

import base64
import binascii
import json
import zlib
from hashlib import sha256
from io import BytesIO
from typing import Literal

import pandas as pd
from pydantic import model_validator

from quant_lab.study_data import COLUMNS, audit

from .contracts import Model, canonical, digest
from .isolated_study_contract import (
    MAX_WIRE,
    PILOT_DATASET,
    PILOT_PARQUET,
    CaseResult,
    Hash,
    Plan,
    _nonfinite,
    _unique,
    safe_member,
)

DRAFT = "examples/orchestration/phase-5-5a/historical-authorization.draft.json"
CANDLES = "inputs/historical-candles.json"
FROZEN_PLAN = "07b99935aac61b237f622ecfb41c8a00350864d1f90d21d4665dd9a623181ded"
MANIFEST_SHA = "1cafa7db033f47faa227620398b3b646113cf9cec85f637d48586103f0639b42"
# A single case cannot allocate more than this even from a hostile compressed stream.
CASE_LIMIT = 2 * 1024 * 1024
DATA_LIMIT = 2 * 1024 * 1024


class BlockedDataset(ValueError):
    """A missing, altered or unsuitable frozen dataset."""


class Job(Model):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["SYNTHETIC", "HISTORICAL"]
    plan: Plan
    candles_sha256: Hash
    manifest_sha256: Hash | None
    supervisor_sha256: Hash
    closure: dict[str, Hash]

    @model_validator(mode="after")
    def scope(self):
        if (
            digest(canonical(self.plan.model_dump(mode="json"))) != FROZEN_PLAN
            or self.manifest_sha256 != (MANIFEST_SHA if self.mode == "HISTORICAL" else None)
            or not 0 < len(self.closure) <= 64
            or any(not safe_member(path) for path in self.closure)
            or self.closure.get(CANDLES) != self.candles_sha256
            or self.closure.get("src/quant_lab/study_backend.py") != self.plan.engine_sha256
        ):
            raise ValueError("Job does not match the frozen pilot scope")
        return self


def parse(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid bounded JSON") from exc


def frozen_plan(repo):
    plan = Plan.model_validate_json(canonical(parse((repo / DRAFT).read_bytes())["plan"]))
    if digest(canonical(plan.model_dump(mode="json"))) != FROZEN_PLAN:
        raise ValueError("Frozen historical draft changed")
    return plan


def hash_bytes(raw):
    return sha256(raw).hexdigest()


def plan_sha(job):
    return digest(canonical(job.model_dump(mode="json")))


def validate_frame(frame, cases):
    if (
        list(frame.columns) != COLUMNS
        or not isinstance(frame.index, pd.DatetimeIndex)
        or any(dtype.kind not in "iuf" for dtype in frame.dtypes)
        or not 1 <= len(frame) <= 12000
        or frame.index.hasnans
        or str(frame.index.tz) != "UTC"
        or frame.index[-1] - frame.index[0] > pd.Timedelta(hours=12000)
    ):
        raise BlockedDataset("BLOCKED_DATASET: invalid UTC OHLCV schema or row count")
    report = audit(frame, "BTCUSDT", "1h")
    if report["status"] != "VALID":
        raise BlockedDataset(
            f"BLOCKED_DATASET: OHLCV audit failed ({report['issues']}, "
            f"gaps={report['missing_bars']})"
        )
    for case in cases:
        window(frame, case)
    return report


def window(frame, case):
    start = pd.Timestamp(case.start).tz_convert("UTC") - pd.Timedelta(hours=case.warmup)
    stop = pd.Timestamp(case.end).tz_convert("UTC")
    selected = frame.loc[(frame.index >= start) & (frame.index < stop)]
    if len(selected) != case.bars + case.warmup or selected.index[0] != start:
        raise BlockedDataset(f"BLOCKED_DATASET: incomplete window or warmup for {case.id}")
    return selected


def preflight_dataset(repo, cases):
    root = repo / "data/history" / PILOT_DATASET
    try:
        with (root / "candles.parquet").open("rb") as stream:
            parquet = stream.read(DATA_LIMIT)
        with (root / "manifest.json").open("rb") as stream:
            raw_manifest = stream.read(DATA_LIMIT)
    except OSError as exc:
        raise BlockedDataset("BLOCKED_DATASET: frozen local bundle is unavailable") from exc
    if hash_bytes(parquet) != PILOT_PARQUET or hash_bytes(raw_manifest) != MANIFEST_SHA:
        raise BlockedDataset("BLOCKED_DATASET: dataset or manifest SHA-256 mismatch")
    manifest = parse(raw_manifest)
    request = manifest["request"]
    if (
        manifest["dataset_id"] != PILOT_DATASET
        or manifest["parquet_sha256"] != PILOT_PARQUET
        or (request["symbol"], request["timeframe"], request["market_type"])
        != ("BTC/USDT", "1h", "spot")
    ):
        raise BlockedDataset("BLOCKED_DATASET: manifest identity mismatch")
    frame = pd.read_parquet(BytesIO(parquet))
    report = validate_frame(frame, cases)
    if manifest["rows"] != len(frame):
        raise BlockedDataset("BLOCKED_DATASET: manifest row count mismatch")
    return frame, {
        "dataset_id": PILOT_DATASET,
        "parquet_sha256": PILOT_PARQUET,
        "manifest_sha256": MANIFEST_SHA,
        "ohlcv_audit": report,
        "windows": [
            {
                "case": c.id,
                "bars": c.bars,
                "warmup": c.warmup,
                "start": c.start.isoformat(),
                "end_exclusive": c.end.isoformat(),
            }
            for c in cases
        ],
    }


def candles_bytes(frame, cases):
    validate_frame(frame, cases)
    first = min(c.start - pd.Timedelta(hours=c.warmup) for c in cases)
    last = max(c.end for c in cases)
    frame = frame.loc[(frame.index >= first) & (frame.index < last)]
    return canonical(
        {"start": frame.index[0].isoformat(), "ohlcv": frame.to_numpy().tolist()}
    ).encode()


def read_candles(raw, job):
    if not 0 < len(raw) < DATA_LIMIT or hash_bytes(raw) != job.candles_sha256:
        raise BlockedDataset("BLOCKED_DATASET: projected candles do not match the job")
    value = parse(raw)
    if (
        not isinstance(value, dict)
        or value.keys() != {"start", "ohlcv"}
        or not isinstance(value["start"], str)
        or not isinstance(value["ohlcv"], list)
        or not 1 <= len(value["ohlcv"]) <= 12000
    ):
        raise BlockedDataset("BLOCKED_DATASET: malformed projected candles")
    frame = pd.DataFrame(
        value["ohlcv"],
        columns=COLUMNS,
        index=pd.date_range(
            pd.Timestamp(value["start"]),
            periods=len(value["ohlcv"]),
            freq="h",
        ),
    )
    validate_frame(frame, job.plan.cases)
    return frame


def encode_transport(job, cases):
    parts = []
    for case, value in zip(job.plan.cases, cases, strict=True):
        raw = canonical(value).encode()
        if len(raw) >= CASE_LIMIT:
            raise ValueError("Historical transport part exceeds expansion limit")
        parts.append(
            {
                "id": case.id,
                "size": len(raw),
                "sha256": hash_bytes(raw),
                "zlib": base64.b64encode(zlib.compress(raw, level=9)).decode("ascii"),
            }
        )
    output = canonical(
        {"schema_version": "1.0", "job_sha256": plan_sha(job), "parts": parts}
    ).encode()
    if len(output) >= MAX_WIRE:
        raise ValueError("Historical transport exceeds wire limit")
    return output


def decode_transport(raw, job):
    if not 0 < len(raw) < MAX_WIRE:
        raise ValueError("Historical transport exceeds wire limit")
    document = parse(raw)
    if (
        not isinstance(document, dict)
        or document.keys() != {"schema_version", "job_sha256", "parts"}
        or document["schema_version"] != "1.0"
        or document["job_sha256"] != plan_sha(job)
        or not isinstance(document["parts"], list)
        or len(document["parts"]) != 6
    ):
        raise ValueError("Invalid historical transport identity or cardinality")
    for case, part in zip(job.plan.cases, document["parts"], strict=True):
        if (
            not isinstance(part, dict)
            or part.keys() != {"id", "size", "sha256", "zlib"}
            or part["id"] != case.id
            or type(part["size"]) is not int
            or not 0 < part["size"] < CASE_LIMIT
            or not isinstance(part["zlib"], str)
        ):
            raise ValueError("Invalid historical transport part")
        try:
            compressed = base64.b64decode(part["zlib"], validate=True)
            stream = zlib.decompressobj()
            payload = stream.decompress(compressed, part["size"] + 1)
        except (binascii.Error, zlib.error, ValueError) as exc:
            raise ValueError("Invalid historical transport encoding") from exc
        if (
            not stream.eof
            or stream.unused_data
            or stream.unconsumed_tail
            or len(payload) != part["size"]
            or hash_bytes(payload) != part["sha256"]
        ):
            raise ValueError("Historical transport part size, hash or stream mismatch")
        member = CaseResult.model_validate_json(canonical(parse(payload)))
        if (member.id, member.segment, member.scenario, member.costs) != (
            case.id,
            case.segment,
            case.scenario,
            case.costs,
        ):
            raise ValueError("Historical result case changed")
        yield case, member
