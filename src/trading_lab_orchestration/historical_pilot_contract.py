"""Frozen inputs and bounded transport for the isolated Issue #3 historical pilot."""

import base64
import binascii
import json
import zlib
from datetime import date
from hashlib import sha256
from io import BytesIO
from typing import Literal

import pandas as pd
from pydantic import model_validator

from quant_lab.study_data import COLUMNS, audit

from .contracts import Model, canonical, digest
from .isolated_study_contract import (
    PILOT_DATASET,
    PILOT_PARQUET,
    SCHEDULE,
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
BLOCK_BYTES = 32 * 1024
HEADER_MAX = 256  # Includes terminal newline, excludes the base64 block body.
FLOAT_BYTES = 24  # Canonical CPython binary64 representation, including sign and exponent.
EVENT_BYTES = 1024  # Covers either TradeRecord or RejectionRecord in canonical form.
METADATA_BYTES = 4096


def case_bound(bars):
    return METADATA_BYTES + (bars - 1) * (EVENT_BYTES + 1) + 2 * (bars + 1) * (FLOAT_BYTES + 1)


def block_count(size):
    return (size + BLOCK_BYTES - 1) // BLOCK_BYTES


def base64_bound(size):
    return 4 * ((size + 2) // 3)


def _wire_case_bound(size):
    # At most four bytes of extra base64 rounding per independently encoded block.
    return HEADER_MAX + base64_bound(size) + block_count(size) * (HEADER_MAX + 4)


CASE_BARS = tuple(
    24 * (date.fromisoformat(end) - date.fromisoformat(start)).days
    for start, end in SCHEDULE.values()
    for _ in range(2)
)
WIRE_MAX = HEADER_MAX + sum(_wire_case_bound(case_bound(bars)) for bars in CASE_BARS)
WIRE_LIMIT = WIRE_MAX + 1  # The supervisor uses an exclusive capture limit.
TRANSPORT_VERSION = "2.0"
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


def _line(value, *, payload_bytes=0):
    raw = canonical(value).encode() + b"\n"
    if len(raw) > HEADER_MAX + payload_bytes:
        raise ValueError("Historical transport header exceeds its bound")
    return raw


def iter_transport(job, cases):
    yield _line({"schema_version": TRANSPORT_VERSION, "job_sha256": plan_sha(job)})
    for case, value in zip(job.plan.cases, cases, strict=True):
        payload = canonical(value).encode()
        if not 0 < len(payload) <= case_bound(case.bars):
            raise ValueError("Historical case exceeds its serialized bound")
        blocks = block_count(len(payload))
        yield _line(
            {"id": case.id, "bytes": len(payload), "blocks": blocks, "sha256": hash_bytes(payload)}
        )
        for index, start in enumerate(range(0, len(payload), BLOCK_BYTES)):
            block = payload[start : start + BLOCK_BYTES]
            compressed = zlib.compress(block, level=6)
            codec, stored = ("zlib", compressed) if len(compressed) < len(block) else ("raw", block)
            data = base64.b64encode(stored).decode("ascii")
            yield _line(
                {
                    "id": case.id,
                    "index": index,
                    "codec": codec,
                    "sha256": hash_bytes(block),
                    "data": data,
                },
                payload_bytes=len(data),
            )


def encode_transport(job, cases):
    return b"".join(iter_transport(job, cases))


def _read_line(stream, limit, keys):
    raw = stream.readline(limit + 1)
    if not raw.endswith(b"\n") or len(raw) > limit:
        raise ValueError("Missing, oversized or truncated historical transport frame")
    frame = parse(raw)
    if not isinstance(frame, dict) or frame.keys() != keys:
        raise ValueError("Invalid historical transport frame")
    return frame


def _decode_block(frame, expected):
    if not isinstance(frame["data"], str) or len(frame["data"]) > base64_bound(expected):
        raise ValueError("Historical wire block exceeds size bound")
    try:
        stored = base64.b64decode(frame["data"], validate=True)
        if frame["codec"] == "raw":
            block = stored
        elif frame["codec"] == "zlib" and len(stored) < expected:
            decoder = zlib.decompressobj()
            block = decoder.decompress(stored, expected + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError("Invalid bounded zlib stream")
        else:
            raise ValueError("Unsupported or oversized historical block encoding")
    except (binascii.Error, zlib.error) as exc:
        raise ValueError("Invalid historical block encoding") from exc
    if len(block) != expected or hash_bytes(block) != frame["sha256"]:
        raise ValueError("Historical block size or hash mismatch")
    return block


def decode_transport(raw, job):
    if not 0 < len(raw) <= WIRE_MAX:
        raise ValueError("Historical transport exceeds wire limit")
    stream = BytesIO(raw)
    header = _read_line(stream, HEADER_MAX, {"schema_version", "job_sha256"})
    if header != {"schema_version": TRANSPORT_VERSION, "job_sha256": plan_sha(job)}:
        raise ValueError("Invalid historical transport identity")
    for case in job.plan.cases:
        part = _read_line(stream, HEADER_MAX, {"id", "bytes", "blocks", "sha256"})
        size = part["bytes"]
        if (
            part["id"] != case.id
            or type(size) is not int
            or not 0 < size <= case_bound(case.bars)
            or type(part["blocks"]) is not int
            or part["blocks"] != block_count(size)
        ):
            raise ValueError("Invalid historical case manifest")
        payload = bytearray()
        for index in range(part["blocks"]):
            expected = min(BLOCK_BYTES, size - len(payload))
            frame = _read_line(
                stream,
                HEADER_MAX + base64_bound(expected),
                {"id", "index", "codec", "sha256", "data"},
            )
            if frame["id"] != case.id or type(frame["index"]) is not int or frame["index"] != index:
                raise ValueError("Missing, repeated or out-of-order historical block")
            payload.extend(_decode_block(frame, expected))
        if hash_bytes(payload) != part["sha256"]:
            raise ValueError("Historical case SHA-256 mismatch")
        member = CaseResult.model_validate_json(canonical(parse(payload)))
        if (
            (member.id, member.segment, member.scenario, member.costs)
            != (case.id, case.segment, case.scenario, case.costs)
            or len(member.trades) + len(member.rejections) > case.bars - 1
            or len(member.equity) != case.bars + 1
            or len(member.exposure) != case.bars + 1
        ):
            raise ValueError("Historical result case changed or exceeds its cardinality")
        yield case, member
    if stream.read(1):
        raise ValueError("Unexpected data after the six historical cases")
