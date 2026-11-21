"""Strict public query contracts. No execution or model dependencies."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import JsonValue, canonical, fingerprint

Identity = Annotated[str, Field(min_length=1, max_length=160)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Page(Query):
    page_size: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, min_length=1, max_length=8192)
    sort: Literal["id", "-id"] = "id"


class StrategyFilters(Query):
    strategy_id: Identity | None = None
    family: Identity | None = None
    asset: Identity | None = None
    timeframe: Identity | None = None


class ExperimentFilters(Query):
    strategy_id: Identity | None = None
    version_id: Identity | None = None
    asset: Identity | None = None
    timeframe: Identity | None = None
    market_type: Identity | None = None
    experiment_id: Identity | None = None
    holdout: Literal["CONSUMED", "UNOBSERVED", "UNKNOWN"] | None = None
    capital_policy: Literal["RESET_PER_SEGMENT", "CONTINUOUS", "UNKNOWN"] | None = None
    parameters: dict[str, JsonValue] | None = None
    parameter_fingerprint: Digest | None = None

    @model_validator(mode="after")
    def parameter_identity(self):
        if self.parameters is not None:
            digest = fingerprint(self.parameters)
            if self.parameter_fingerprint is not None and self.parameter_fingerprint != digest:
                raise ValueError("Parameter fingerprint mismatch")
            object.__setattr__(self, "parameter_fingerprint", digest)
        return self


class CaseFilters(Query):
    segment: Identity | None = None
    scenario: Identity | None = None
    period_start_utc: str | None = None
    period_end_utc: str | None = None
    asset: Identity | None = None
    timeframe: Identity | None = None
    version_id: Identity | None = None
    status: Literal["COMPLETE", "FAILED", "BLOCKED", "UNKNOWN"] | None = None
    audit_status: Literal["SOURCE_AUDITED", "UNVERIFIED"] | None = None

    @field_validator("period_start_utc", "period_end_utc")
    @classmethod
    def utc(cls, value):
        if value is None:
            return value
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() != UTC.utcoffset(None):
            raise ValueError("UTC required")
        return parsed.isoformat().replace("+00:00", "Z")


class ResearchCriteria(ExperimentFilters):
    # Full frozen experiment fingerprint, not an inferred semantic similarity.
    definition_fingerprint: Digest | None = None


class ReadFailure(ValueError):
    def __init__(self, code: str, reason: str):
        self.code, self.reason = code, reason
        super().__init__(reason)


_PRIVATE_KEY = re.compile(
    r"(?i)(password|secret|token|api.?key|private.?key|access.?key|credential|permit.?id|operator.?sid)"
)
_PRIVATE_VALUE = re.compile(
    r"(?i)([a-z]:[\\/]|\\\\|(?:^|\s)/\S+|"
    r"S-1-\d+(?:-\d+)+|(?:sk-|ghp_|github_pat_)[a-z0-9_-]{8,}|"
    r"(?:pilot_launch_|pilot_auth_|attempt_)[a-z0-9]+|Bearer\s+\S+|"
    r"-----BEGIN .*PRIVATE KEY-----)"
)


def public_data(value):
    """Project out local locators; redact recognized sensitive text, never read files."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _PRIVATE_KEY.search(key) else public_data(item)
            for key, item in value.items()
            if key not in {"reference", "evidence_reference", "source", "metadata"}
            and not _PRIVATE_VALUE.search(key)
        }
    if isinstance(value, list):
        return [public_data(item) for item in value]
    if isinstance(value, str) and _PRIVATE_VALUE.search(value):
        return "[REDACTED]"
    return value


def json_size(value):
    return len(canonical(value).encode("utf-8"))
