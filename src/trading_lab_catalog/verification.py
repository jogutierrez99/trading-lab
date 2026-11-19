"""Bounded declarative reads. Hashes bind captured bytes, never a second read."""

import hashlib
import json
from pathlib import Path


class BlockedSource(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, limit=16 * 1024 * 1024):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise BlockedSource("Linked source path")
    if path.stat().st_size > limit:
        raise BlockedSource("Source exceeds size limit")
    with path.open("rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise BlockedSource("Source exceeds size limit")
    return data


def parse(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise BlockedSource("Duplicate JSON key")
            value[key] = item
        return value

    def nonfinite(_):
        raise BlockedSource("Nonfinite JSON number")

    document = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    # JSON exponent overflow (1e400) is parsed as infinity without invoking
    # parse_constant, so check the complete decoded document as well.
    json.dumps(document, allow_nan=False)
    return document
