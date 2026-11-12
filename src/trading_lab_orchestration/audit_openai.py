"""Explicit, single-request OpenAI supplement to verified deterministic audits."""

import http.client
import json
import re
import shlex
from datetime import UTC, date, datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from pydantic import ValidationError

from .audit import Auditor
from .audit_contracts import AuditRequest, AuditVerdict, ModelReview
from .audit_evidence import Evidence, review
from .audit_model import PROFILE, validate_model_review
from .contracts import canonical, digest
from .processes import coordinator_lock
from .store import utc_now
from .workspaces import file_hash, write_json

DEFAULT_MODEL = "gpt-6.1-sol"
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing?latest-pricing-expanded=true"
PRICE_REVIEWED = date(2026, 11, 5)
PRICE_EXPIRES = date(2026, 11, 12)
INPUT_CAP = 1_050_000  # Full published context bound, including framing/schema.
OUTPUT_CAP = 1200  # Visible plus reasoning tokens.
EUR_PER_USD_CEILING = Decimal("1.25")
REGIONAL_CEILING = Decimal("1.10")
TAX_CEILING = Decimal("1.25")
SAFE_REFS = {
    "execution_receipt",
    "implementation_receipt",
    "native:summary.json",
    "native:metrics.csv",
    "native:outcome.json",
    "native:plan.json",
    "native:run.json",
}


def load_openai_key(path, name="OPENAI_API_KEY"):
    """Read only the named assignment. Keep the value out of os.environ."""
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError):
        raise ValueError("Cannot read local OpenAI key configuration") from None
    if name not in {"OPENAI_API_KEY", "OPENAI_ADMIN_KEY"}:
        raise ValueError("Unsupported OpenAI key assignment")
    values = []
    for line in lines:
        match = re.fullmatch(r"\s*(?:export\s+)?" + name + r"\s*=(.*)", line)
        if match:
            try:
                parts = shlex.split(match[1], comments=True)
            except ValueError:
                raise ValueError("Invalid " + name + " assignment") from None
            if len(parts) > 1:
                raise ValueError("Invalid " + name + " assignment")
            values.append(parts[0] if parts else "")
    if len(values) > 1:
        raise ValueError("Ambiguous " + name + " assignment")
    return values[0] if values and values[0] else None


def cost_breakdown(input_tokens, output_tokens):
    # Charge all input at the highest cache-write rate, without assuming cache discounts.
    long = input_tokens > 272_000
    input_rate, output_rate = (10, 15) if long else (5, 10)
    input_usd = Decimal(input_tokens * input_rate) / 1_000_000
    output_usd = Decimal(output_tokens * output_rate) / 1_000_000
    eur = (input_usd + output_usd) * EUR_PER_USD_CEILING * REGIONAL_CEILING * TAX_CEILING
    return {
        "input_usd_per_million": input_rate,
        "output_usd_per_million": output_rate,
        "input_usd": str(input_usd),
        "output_usd": str(output_usd),
        "unrounded_eur": str(eur),
        "maximum_cents": int((eur * 100).to_integral_value(rounding=ROUND_CEILING)),
    }


def cost_cents(input_tokens, output_tokens):
    return cost_breakdown(input_tokens, output_tokens)["maximum_cents"]


def quote(model):
    if model != DEFAULT_MODEL:
        raise ValueError("No verified price and context profile for the selected model")
    today = datetime.now(UTC).date()
    if not PRICE_REVIEWED <= today <= PRICE_EXPIRES:
        raise ValueError("OpenAI price profile expired or not yet valid; review official rates")
    return {
        "model": model,
        "service_tier": "default",
        "input_token_ceiling": INPUT_CAP,
        "output_token_limit": OUTPUT_CAP,
        **cost_breakdown(INPUT_CAP, OUTPUT_CAP),
        "eur_per_usd_ceiling": str(EUR_PER_USD_CEILING),
        "regional_multiplier_ceiling": str(REGIONAL_CEILING),
        "tax_multiplier_ceiling": str(TAX_CEILING),
        "price_source": PRICE_SOURCE,
        "price_reviewed_utc": str(PRICE_REVIEWED),
        "price_expires_utc": str(PRICE_EXPIRES),
    }


def responses_body(model, packet):
    schema = ModelReview.model_json_schema()
    # Structured Outputs requires all properties. Local ModelReview still validates.
    schema["required"] = list(schema["properties"])
    for prop in schema["properties"].values():
        prop.pop("default", None)
    return canonical(
        {
            "model": model,
            "instructions": PROFILE["instructions"]
            + " Use at most three short findings and three uncertainties.",
            "input": canonical(packet),
            "store": False,
            "service_tier": "default",
            "truncation": "disabled",
            "max_output_tokens": OUTPUT_CAP,
            "tools": [],
            "reasoning": {"effort": "low"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "model_review",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
    ).encode("utf-8")


class OpenAIResponses:
    name = "openai"

    def __init__(self, key, model=DEFAULT_MODEL, *, billing_scope=None):
        self._key = key
        self.model = model
        self.billing_scope = tuple(billing_scope) if billing_scope else None
        if self.billing_scope:
            organization, project = self.billing_scope
            if not re.fullmatch(r"org-[\w-]+", organization, re.ASCII) or not re.fullmatch(
                r"proj_[\w-]+", project, re.ASCII
            ):
                raise ValueError("Billing scope requires an organization ID and project ID")

    def call(self, packet):
        return self.post(responses_body(self.model, packet))

    def post(self, body):
        conn = http.client.HTTPSConnection("api.openai.com", timeout=45)
        try:
            headers = {"Authorization": "Bearer " + self._key, "Content-Type": "application/json"}
            if self.billing_scope:
                organization, project = self.billing_scope
                headers.update({"OpenAI-Organization": organization, "OpenAI-Project": project})
            conn.request(
                "POST",
                "/v1/responses",
                body,
                headers,
            )
            response = conn.getresponse()
            if response.status != 200:
                raise ValueError("OPENAI_HTTP_ERROR")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("OPENAI_RESPONSE_LIMIT")
            return json.loads(raw)
        finally:
            conn.close()


def evidence_packet(verdict, observations, refs):
    keys = (
        "symbol",
        "period",
        "mode",
        "scenario",
        "closed_trades",
        "return_pct",
        "max_drawdown_pct",
    )
    results = []
    for item in observations["native_results"]:
        metrics = item["result"]["metrics"]
        results.append({key: metrics[key] for key in keys if key in metrics})
    counts = ("total_backtests", "valid_backtests", "failed_backtests", "filter_rejected_backtests")
    packet = {
        "run_id": verdict.run_id,
        "synthetic": observations["synthetic"],
        "protocol": observations["protocol"],
        "cases": results,
        "counts": {key: observations["summary"].get(key) for key in counts},
        "references": {key: refs[key]["sha256"] for key in sorted(SAFE_REFS & refs.keys())},
        "limitations": [
            "Technical evidence only",
            "Existing classifications are authoritative",
            "Independent economic validation is absent",
        ],
    }
    if len(canonical(packet).encode("utf-8")) > 16000 or not packet["references"]:
        raise ValueError("Compact verified evidence limit exceeded or references unavailable")
    return packet


def parse_usage(response, model, *, input_cap=INPUT_CAP, output_cap=OUTPUT_CAP):
    if response.get("model") != model or response.get("service_tier") != "default":
        raise ValueError("Unexpected provider model or pricing tier")
    usage = response["usage"]
    inp, out = usage["input_tokens"], usage["output_tokens"]
    if (
        type(inp) is not int
        or type(out) is not int
        or not (0 <= inp <= input_cap and 0 <= out <= output_cap)
    ):
        raise ValueError("Provider usage missing or outside reservation")
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens")
    reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens")
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cached_input_tokens": cached if type(cached) is int and 0 <= cached <= inp else None,
        "reasoning_tokens": reasoning if type(reasoning) is int and 0 <= reasoning <= out else None,
    }


def response_text(response):
    if response.get("status") != "completed":
        raise ValueError("OpenAI review incomplete")
    parts = []
    for item in response["output"]:
        if item["type"] == "reasoning":
            continue
        if item["type"] != "message" or item.get("role") != "assistant":
            raise ValueError("Unexpected review output item")
        parts.extend(item["content"])
    if len(parts) != 1 or parts[0]["type"] != "output_text":
        raise ValueError("OpenAI refused or returned no single structured review")
    return parts[0]["text"]


def parse_review(response, packet):
    result = validate_model_review(response_text(response), packet["references"])
    return result.model_dump(mode="json")


def verified_source(source, audit_id):
    original = Auditor(source).inspect(audit_id)
    verdict = AuditVerdict.model_validate(original["verdict"])
    if (
        verdict.effective_review_mode != "DETERMINISTIC_ONLY"
        or verdict.audit_status != "COMPLETED_WITH_LIMITATIONS"
    ):
        raise ValueError("Verified deterministic audit required before OpenAI review")
    request = AuditRequest.model_validate_json(original["request_json"])
    evidence = Evidence(request)
    observations = review(source, request, evidence)  # No rerun or strategy import.
    packet = evidence_packet(verdict, observations, evidence.refs)
    return original, request, evidence, packet


def supplement(source, budget, audit_id, destination, provider, maximum_cents):
    from .billing_snapshots import capture_baseline

    pricing = quote(provider.model)
    if maximum_cents != pricing["maximum_cents"]:
        raise ValueError("Confirm the exact reservation shown by the offline diagnostic")
    original, request, evidence, packet = verified_source(source, audit_id)
    destination = Path(destination).resolve()
    protected = (
        Path(original["root"]).resolve(),
        source.path.parent,
        budget.store.path.parent,
        Path(__file__).resolve().parents[2],
    )
    if any(
        destination.is_relative_to(path) or path.is_relative_to(destination) for path in protected
    ):
        raise ValueError("Review dossier must be separate from databases and historical evidence")
    with source.connection() as conn:
        execution = conn.execute(
            "SELECT root,attempt_id FROM executions WHERE execution_id=?", (request.execution_id,)
        ).fetchone()
        attempt = conn.execute(
            "SELECT root FROM attempts WHERE attempt_id=?", (execution["attempt_id"],)
        ).fetchone()
    if any(destination.is_relative_to(Path(row["root"]).resolve()) for row in (execution, attempt)):
        raise ValueError("Review dossier cannot be inside execution or implementation evidence")
    purpose = "openai-audit-v1:" + request.execution_id
    with coordinator_lock(budget.store.path.with_suffix(".openai-audit.lock")):
        if destination.exists():
            raise ValueError("Review dossier already exists; inspect it without sending again")
        evidence.recheck()
        baseline = capture_baseline(budget, provider, maximum_cents)
        call_id = budget.reserve(provider.name, purpose, maximum_cents, once=True)
        destination.mkdir(parents=True, exist_ok=False)
        intent = {
            "schema_version": "1.0",
            "review_mode": "MODEL_ASSISTED",
            "call_id": call_id,
            "origin_audit_id": audit_id,
            "origin_verdict_sha256": original["verdict_sha256"],
            "origin_execution_id": request.execution_id,
            "run_id": request.run_id,
            "pricing": pricing,
            "evidence_packet": packet,
            "created_at_utc": utc_now(),
            **baseline,
        }
        write_json(destination / "review_request.json", intent)
        receipt = {
            **intent,
            "request_sha256": file_hash(destination / "review_request.json"),
            "billing_status": "UNKNOWN",
            "calculated_cents": None,
            "usage": None,
            "invoice_reconciled_cents": None,
            "review": None,
        }
        try:
            response = provider.call(packet)
            usage = parse_usage(response, provider.model)
            receipt.update(
                usage=usage,
                billing_status="CALCULATED_PENDING_RECONCILIATION",
                calculated_cents=cost_cents(usage["input_tokens"], usage["output_tokens"]),
            )
            try:
                receipt.update(status="COMPLETED", review=parse_review(response, packet))
            except (ValidationError, ValueError, TypeError, KeyError):
                receipt.update(
                    status="INVALID_REVIEW", failure="Output or reference validation failed"
                )
        except Exception as exc:
            receipt.update(status="UNKNOWN_PROVIDER_OUTCOME", failure=type(exc).__name__)
        budget.settle(
            call_id,
            None,
            canonical(
                {
                    k: receipt[k]
                    for k in (
                        "billing_status",
                        "calculated_cents",
                        "usage",
                        "pricing",
                        "status",
                    )
                }
                | {"review_receipt_sha256": digest(canonical(receipt))}
                | baseline
            ),
        )
        write_json(destination / "review_receipt.json", receipt)
        write_json(
            destination / "hashes.json",
            {
                name: file_hash(destination / name)
                for name in ("review_request.json", "review_receipt.json")
            },
        )
        return receipt
