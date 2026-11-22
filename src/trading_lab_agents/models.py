"""TLAgents contracts 1.0. Proposals are not HypothesisManifest or authorizations."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import canonical, digest

NAMESPACE = "TLAgents"
INSTRUCTIONS_VERSION = "TLAgents.researcher/1.0"
INPUT_LIMIT = 64 * 1024
OUTPUT_LIMIT = 32 * 1024


def not_latest(value: str) -> str:
    if value.casefold() == "latest":
        raise ValueError("An exact identifier is required")
    return value


ID = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"), AfterValidator(not_latest)
]
CatalogID = Annotated[str, Field(min_length=1, max_length=160)]
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("Nonblank text required")
    return value


Text = Annotated[str, Field(min_length=1, max_length=4000), AfterValidator(not_blank)]
Texts = Annotated[list[Text], Field(max_length=20)]
IDs = Annotated[list[ID], Field(max_length=20)]


def utc(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(None):
        raise ValueError("Explicit UTC required")
    return value


UTCText = Annotated[Text, AfterValidator(utc)]


def ordered(start: str | None, end: str | None) -> None:
    if (start is None) != (end is None):
        raise ValueError("Both interval endpoints are required or unknown")
    if start is not None and datetime.fromisoformat(start) >= datetime.fromisoformat(end):
        raise ValueError("Interval must be increasing")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class PublicEvidence(Contract):
    reference_id: ID
    kind: Text
    sha256: SHA | None
    verification: Literal["UNVERIFIED", "HASH_VERIFIED", "SOURCE_AUDITED"]
    limitations: Texts


class CatalogRef(Contract):
    entity_type: Literal["strategy", "version", "experiment", "run", "case", "artifact", "decision"]
    entity_id: CatalogID
    record_fingerprint: SHA | None
    checkpoint: SHA | None
    effective_status: Literal["UNVERIFIED", "HASH_VERIFIED", "SOURCE_AUDITED", "UNKNOWN"]


class Market(Contract):
    asset: Text
    market_type: Text
    timeframe: Text
    requested_years: Annotated[int, Field(ge=1, le=30)] | None
    coverage_start_utc: UTCText | None
    coverage_end_utc: UTCText | None

    @model_validator(mode="after")
    def coverage(self) -> Self:
        ordered(self.coverage_start_utc, self.coverage_end_utc)
        return self


class Discovery(Contract):
    statistics_reference_id: ID | None
    searches_count: Annotated[int, Field(ge=0)] | None
    period_start_utc: UTCText | None
    period_end_utc: UTCText | None

    @model_validator(mode="after")
    def period(self) -> Self:
        ordered(self.period_start_utc, self.period_end_utc)
        return self


class ResearchRequest(Contract):
    schema_version: Literal["1.0"]
    contract_kind: Literal["ResearchRequest"]
    request_id: ID
    flow: Literal["FLOW1", "FLOW2"]
    objective: Text
    market: Market
    source_refs: Annotated[list[PublicEvidence], Field(max_length=20)]
    catalog_context: Annotated[list[CatalogRef], Field(max_length=20)]
    discovery: Discovery
    max_hypotheses: int = Field(ge=1, le=3)
    status: Literal["PREPARED", "BLOCKED"]
    limitations: Texts
    notes: Text | None = None

    @model_validator(mode="after")
    def sources(self) -> Self:
        ids = [r.reference_id for r in self.source_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate source identity")
        refs = [(r.entity_type, r.entity_id) for r in self.catalog_context]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate catalogue reference")
        if self.status == "PREPARED":
            if not ids:
                raise ValueError("Prepared request needs a source")
            if self.flow == "FLOW2" and self.discovery.statistics_reference_id not in ids:
                raise ValueError("Flow 2 requires a referenced statistics source")
        return self


class HypothesisDraft(Contract):
    hypothesis_id: ID
    asset: Text
    market_type: Text
    timeframe: Text
    statement: Text
    justification: Text
    source_ids: IDs
    evidence_ids: IDs
    observable_conditions: Texts
    falsification: Texts
    bias_risks: Annotated[list[Text], Field(min_length=1, max_length=20)]
    limitations: Annotated[list[Text], Field(min_length=1, max_length=20)]
    catalog_refs: Annotated[list[CatalogRef], Field(max_length=20)]
    verification_status: Literal["DECLARED"]


class ResearchHypothesis(Contract):
    schema_version: Literal["1.0"]
    contract_kind: Literal["ResearchHypothesis"]
    request_id: ID
    status: Literal["HYPOTHESIS_PROPOSED", "NO_HYPOTHESIS", "NEEDS_REVIEW"]
    candidates: Annotated[list[HypothesisDraft], Field(max_length=3)]
    rejected_reasons: Texts
    missing_fields: Texts
    notes: Text | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        ids = [c.hypothesis_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate hypothesis identity")
        if self.status == "HYPOTHESIS_PROPOSED":
            if not self.candidates or self.missing_fields:
                raise ValueError("Proposed hypothesis is incomplete")
            if any(not c.observable_conditions or not c.falsification for c in self.candidates):
                raise ValueError("Conditions and falsification required")
        if self.status == "NO_HYPOTHESIS" and self.candidates:
            raise ValueError("NO_HYPOTHESIS cannot contain candidates")
        if self.status == "NEEDS_REVIEW" and not self.missing_fields:
            raise ValueError("Review requires explicit missing fields")
        return self


def decode(raw: bytes, model: type[Contract], limit: int) -> Contract:
    """Validate captured UTF-8 bytes, including duplicate keys and exponent overflow."""
    if type(raw) is not bytes or len(raw) > limit:
        raise ValueError("Invalid bounded byte input")
    text = raw.decode("utf-8")
    try:
        payload = parse(text)
    except (RecursionError, OverflowError):
        raise ValueError("JSON nesting or numeric representation exceeds parser limits") from None
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return model.model_validate(payload)


def identity(kind: str, value: object) -> str:
    """Orchestration canonicalization, explicitly namespaced; not catalogue fingerprints."""
    return digest(
        canonical({"namespace": NAMESPACE, "schema_version": "1.0", "kind": kind, "payload": value})
    )
