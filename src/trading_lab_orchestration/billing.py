"""Attribute OpenAI charges from independent billing evidence, without model calls."""

import csv
import hashlib
import http.client
import io
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, DecimalException
from urllib.parse import urlencode

from .audit_openai import EUR_PER_USD_CEILING, REGIONAL_CEILING, TAX_CEILING
from .contracts import canonical

MAX_BYTES = 4 * 1024 * 1024
REDUCED = "gpt-4o-mini-2024-07-18"


class EvidenceUnavailable(ValueError):
    def __init__(self, message, code="ATTRIBUTION_UNCERTAIN"):
        super().__init__(message)
        self.code = code


def _number(value):
    try:
        number = Decimal(str(value))
    except DecimalException as exc:
        raise EvidenceUnavailable("Invalid billing number") from exc
    if not number.is_finite() or not 0 <= number <= 10**12:
        raise EvidenceUnavailable("Invalid or negative billing number")
    return number


def _integer(value):
    number = _number(value)
    if number != number.to_integral_value():
        raise EvidenceUnavailable("Usage counts must be integers")
    return int(number)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _scope(rows, project, active):
    for row in rows:
        if row.get(active) in (None, ""):
            continue
        if project and not row.get("project_id"):
            raise EvidenceUnavailable("Export or query with project_id grouping on both sources")
        if project is None or row["project_id"] == project:
            yield row


def _usage(rows, project):
    result = Counter()
    for row in _scope(rows, project, "num_model_requests"):
        if not row.get("model") or not row.get("service_tier"):
            raise EvidenceUnavailable("Usage must be grouped by model and service tier")
        key = (row["model"], row["service_tier"])
        for field in ("num_model_requests", "input_tokens", "output_tokens", "input_cached_tokens"):
            result[key, field] += _integer(row.get(field))
    return +result


def _ledger_usage(rows):
    usage = []
    for row in rows:
        try:
            proof = json.loads(row["provenance"])
            if row["status"] == "SETTLED":
                proof = json.loads(proof["prior_calculation"])
            receipt = proof["usage"]
            if receipt["cached_input_tokens"] is None:
                raise ValueError("Unverified cached input count")
            usage.append(
                {
                    "input_tokens": receipt["input_tokens"],
                    "output_tokens": receipt["output_tokens"],
                    "input_cached_tokens": receipt["cached_input_tokens"],
                    "num_model_requests": 1,
                    "model": proof["pricing"]["model"],
                    "service_tier": proof["pricing"]["service_tier"],
                }
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise EvidenceUnavailable(
                "A ledger call in the UTC day lacks verified receipt usage"
            ) from exc
    return usage


def _csv_rows(path, start, active):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise EvidenceUnavailable("CSV exceeds billing evidence size limit")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)) or not {"start_time", "end_time", active} <= set(fields):
        raise EvidenceUnavailable("Unexpected OpenAI CSV headers")
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise EvidenceUnavailable("Invalid OpenAI CSV row")
        left, right = _integer(row["start_time"]), _integer(row["end_time"])
        if left < start + 86400 and right > start:
            if (left, right) != (start, start + 86400):
                raise EvidenceUnavailable("Evidence must contain matching whole UTC-day buckets")
            rows.append(row)
    return rows, {"source": str(path.resolve()), "sha256": _hash(raw)}


def csv_evidence(usage_path, costs_path, start):
    usage, usage_ref = _csv_rows(usage_path, start, "num_model_requests")
    costs, costs_ref = _csv_rows(costs_path, start, "amount_value")
    return usage, costs, {"usage": usage_ref, "costs": costs_ref}


def _get(endpoint, query, key, organization=None):
    conn = http.client.HTTPSConnection("api.openai.com", timeout=15)
    try:
        headers = {"Authorization": "Bearer " + key}
        if organization:
            headers["OpenAI-Organization"] = organization
        conn.request(
            "GET",
            "/v1/organization/" + endpoint + "?" + urlencode(query, doseq=True),
            headers=headers,
        )
        response = conn.getresponse()
        if response.status in (401, 403):
            raise EvidenceUnavailable(
                f"Admin access denied for organization Usage or Costs (HTTP {response.status})",
                "ADMIN_ACCESS_DENIED",
            )
        if response.status != 200:
            raise EvidenceUnavailable(
                f"OpenAI billing unavailable (HTTP {response.status})", "BILLING_UNAVAILABLE"
            )
        return response.read(MAX_BYTES + 1)
    finally:
        conn.close()


def admin_evidence(start, project, *, organization=None, archive=None):
    key = os.environ.get("OPENAI_ADMIN_KEY", "").strip()
    if not key:
        raise EvidenceUnavailable(
            "OPENAI_ADMIN_KEY missing; use the CSV pair or an Admin API key", "ADMIN_KEY_MISSING"
        )
    refs = {}
    tables = []
    for label, endpoint, grouping in (
        ("usage", "usage/completions", ["project_id", "model", "service_tier"]),
        ("costs", "costs", ["project_id", "line_item"]),
    ):
        query = {
            "start_time": start,
            "end_time": start + 86400,
            "bucket_width": "1d",
            "project_ids": [project],
            "group_by": grouping,
            "limit": 1,
        }
        raw = (
            _get(endpoint, query, key, organization) if organization else _get(endpoint, query, key)
        )
        if len(raw) > MAX_BYTES:
            raise EvidenceUnavailable("Admin billing response exceeds size limit")
        rows = _admin_rows(raw, label, start, project, organization)
        if archive is not None:
            archive[label] = raw.decode("utf-8")
        tables.append(rows)
        refs[label] = {
            "source": "/v1/organization/" + endpoint,
            "query": query,
            "sha256": _hash(raw),
        }
    return *tables, refs


def _admin_rows(raw, label, start, project, organization):
    payload = json.loads(raw, parse_float=Decimal)
    if payload["has_more"] is not False or payload.get("next_page"):
        raise EvidenceUnavailable("Admin returned a partial page; use a complete CSV export")
    rows = []
    buckets = payload["data"]
    if len(buckets) > 1:
        raise EvidenceUnavailable("Unexpected Admin bucket count")
    for bucket in buckets:
        if (bucket["start_time"], bucket["end_time"]) != (start, start + 86400):
            raise EvidenceUnavailable("Admin returned an unexpected UTC bucket")
        for row in bucket["results"]:
            if row.get("project_id") != project:
                raise EvidenceUnavailable("Admin returned a different or ungrouped project")
            if label == "costs":
                if organization and row.get("organization_id") != organization:
                    raise EvidenceUnavailable("Admin Costs returned a different organization")
                row = row | {
                    "amount_value": row["amount"]["value"],
                    "amount_currency": row["amount"]["currency"],
                }
            rows.append(row)
    return rows


def _costs(rows, project):
    scoped = list(_scope(rows, project, "amount_value"))
    if not scoped:
        raise EvidenceUnavailable(
            "No billed cost published for this UTC day and scope", "COST_NOT_AVAILABLE"
        )
    if any(row.get("amount_currency", "").lower() != "usd" for row in scoped):
        raise EvidenceUnavailable("Only USD billing evidence is supported")
    return scoped


def _total(rows):
    return sum((_number(row["amount_value"]) for row in rows), Decimal(0))


def _token_lines(rows, target):
    model = target["model"]
    attributed = []
    for field in ("input_tokens", "output_tokens"):
        matches = [row for row in rows if row.get("line_item") == f"{model}, {field}"]
        if len(matches) != 1:
            raise EvidenceUnavailable("Missing or duplicate itemized input/output charge")
        row = matches[0]
        if row.get("quantity_unit") not in {"tokens", "1000_tokens"}:
            raise EvidenceUnavailable("Billed token quantities are unavailable")
        units = 1000 if row["quantity_unit"] == "1000_tokens" else 1
        if _number(row.get("quantity")) * units != _integer(target[field]):
            raise EvidenceUnavailable("Billed quantities do not yet match receipt usage")
        attributed.append(row)
    return _total(attributed)


def _prior_cost_is_anchored(peers, cost_hash):
    for row in peers:
        reference = json.loads(row["provenance"]).get("invoice_reference", "")
        if not isinstance(reference, str):
            continue
        try:
            proof = json.loads(reference)
        except ValueError:
            # Older manual settlements cite a file hash in their provenance text.
            if re.search(rf"\bsha256\s+{cost_hash}\b", reference, re.IGNORECASE):
                return True
        else:
            if (
                isinstance(proof, dict)
                and proof.get("evidence", {}).get("costs", {}).get("sha256") == cost_hash
            ):
                return True
    return False


def _attribute(costs, target, others, peers, baseline, project, exclusive):
    scoped = _costs(costs, project)
    target_standard = target["service_tier"] == "default" and target["input_cached_tokens"] == 0
    # Restrict the itemized path to an isolated, standard text charge. Extra line items
    # could be additional charges or discounts, so never silently discard them.
    if baseline is None and not others and target_standard and len(scoped) == 2:
        if all(row.get("quantity_unit") for row in scoped):
            return _token_lines(scoped, target), "ITEMIZED_BILLED_QUANTITIES", Decimal(0)
    # A daily amount can lag usage. Require an independent amount AND exact agreement
    # with the documented uncached Standard tariff for the reduced profile.
    if target["model"] != REDUCED or not target_standard:
        raise EvidenceUnavailable(
            "Need isolated itemized costs with matching billed quantities for this profile"
        )
    if not exclusive:
        raise EvidenceUnavailable(
            "Grouped USD totals require an exclusive scope containing only the matched Lab calls"
        )
    prior = Decimal(0)
    if others:
        if baseline is None:
            raise EvidenceUnavailable(
                "Grouped costs require a prior Usage and Costs pair for all other calls"
            )
        old_usage, old_costs, old_refs = baseline
        if _usage(old_usage, project) != _usage(others, None):
            raise EvidenceUnavailable(
                "Prior Usage does not exactly account for the other settled calls"
            )
        if not _prior_cost_is_anchored(peers, old_refs["costs"]["sha256"]):
            raise EvidenceUnavailable(
                "Prior Costs hash must be cited in a settled call from the same cohort"
            )
        prior = _total(_costs(old_costs, project))
    elif baseline is not None:
        raise EvidenceUnavailable("Prior evidence supplied but there are no other settled calls")
    expected = (
        Decimal("0.15") * target["input_tokens"] + Decimal("0.60") * target["output_tokens"]
    ) / 1_000_000
    observed = _total(scoped) - prior
    if observed <= 0 or observed != expected:
        raise EvidenceUnavailable(
            "Billed delta does not match the sole new call; costs may lag or include other charges"
        )
    return observed, "MATCHED_BILLING_DELTA", prior


def _availability(budget):
    try:
        return {"available_cents": budget.available(), "budget_blocker": None}
    except ValueError as exc:
        return {"available_cents": None, "budget_blocker": str(exc)}


def reconcile(
    budget,
    call_id,
    *,
    usage_csv=None,
    costs_csv=None,
    prior_usage_csv=None,
    prior_costs_csv=None,
    project=None,
    admin=False,
    exclusive=False,
    apply=False,
    snapshots=False,
):
    if bool(usage_csv) != bool(costs_csv) or bool(prior_usage_csv) != bool(prior_costs_csv):
        raise ValueError("Supply matching Usage and Costs file pairs")
    if admin and (usage_csv or prior_usage_csv or not project):
        raise ValueError("Admin mode requires --project-id and uses only Admin evidence")
    if prior_usage_csv and not usage_csv:
        raise ValueError("Prior CSVs require current CSVs")
    calls = budget.inspect()["calls"]
    row = next((r for r in calls if r["call_id"] == call_id), None)
    if (
        not row
        or row["provider"] != "openai"
        or not row["purpose"].startswith(("openai-audit-v1:", "openai-research-v1:"))
    ):
        raise ValueError("Select an existing OpenAI researcher or auditor call")
    result = {
        "call_id": call_id,
        "ledger_status": row["status"],
        "reserved_cents": row["reserved_cents"],
        "actual_cents": row["actual_cents"],
        "released_now_cents": 0,
        "admin_key_present": bool(os.environ.get("OPENAI_ADMIN_KEY", "").strip()),
    }
    if row["status"] == "SETTLED":
        return result | {"status": "ALREADY_SETTLED"} | _availability(budget)
    try:
        if row["status"] != "UNKNOWN":
            raise EvidenceUnavailable("Call still reserved; wait for the provider receipt")
        day = (
            datetime.fromisoformat(row["created_at_utc"])
            .astimezone(UTC)
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        start = int(day.timestamp())
        peers = [
            other
            for other in calls
            if other["provider"] == "openai"
            and other["call_id"] != call_id
            and day <= datetime.fromisoformat(other["created_at_utc"]) < day + timedelta(days=1)
        ]
        if any(other["status"] != "SETTLED" for other in peers):
            raise EvidenceUnavailable(
                "More than one unsettled OpenAI call in the UTC day; separate evidence required"
            )
        target, *others = _ledger_usage([row, *peers])
        if snapshots:
            from .billing_snapshots import attribute_snapshot

            usd, prior, refs, prior_refs = attribute_snapshot(row, start, project, target, others)
            method = "MATCHED_ITEMIZED_SNAPSHOT_DELTA"
        else:
            if admin:
                evidence = admin_evidence(start, project)
            elif usage_csv:
                evidence = csv_evidence(usage_csv, costs_csv, start)
            else:
                raise EvidenceUnavailable(
                    "Provide a current Usage and Costs pair or select Admin mode"
                )
            usage, costs, refs = evidence
            actual_usage = _usage(usage, project)
            expected_usage = _usage([target, *others], None)
            if actual_usage != expected_usage:
                observed_count = sum(
                    n for (_, field), n in actual_usage.items() if field == "num_model_requests"
                )
                raise EvidenceUnavailable(
                    "Usage does not uniquely match the receipt cohort; "
                    f"observed {observed_count} requests, "
                    f"expected {1 + len(others)} with exact token totals",
                    "USAGE_INCOMPLETE_OR_DIFFERENT_SCOPE"
                    if observed_count < 1 + len(others)
                    else "ATTRIBUTION_UNCERTAIN",
                )
            baseline = (
                csv_evidence(prior_usage_csv, prior_costs_csv, start) if prior_usage_csv else None
            )
            prior_refs = baseline[2] if baseline else None
            usd, method, prior = _attribute(
                costs, target, others, peers, baseline, project, exclusive
            )
    except (
        EvidenceUnavailable,
        OSError,
        http.client.HTTPException,
        csv.Error,
        KeyError,
        TypeError,
        AttributeError,
        ValueError,
    ) as exc:
        reason = (
            str(exc)
            if isinstance(exc, EvidenceUnavailable)
            else f"Billing evidence unavailable or invalid ({type(exc).__name__})"
        )
        return (
            result
            | {
                "status": "BLOCKED",
                "reason": reason,
                "reason_code": (
                    exc.code
                    if isinstance(exc, EvidenceUnavailable)
                    else "BILLING_TIMEOUT"
                    if isinstance(exc, TimeoutError)
                    else "EVIDENCE_UNAVAILABLE_OR_INVALID"
                ),
                "retry_when": (
                    "Refresh both sources once usage and costs include the call; "
                    "use itemized evidence or a narrower scope if ambiguous."
                ),
            }
            | _availability(budget)
        )
    eur = usd * EUR_PER_USD_CEILING * REGIONAL_CEILING * TAX_CEILING
    cents = int((eur * 100).to_integral_value(rounding=ROUND_CEILING))
    if cents > row["reserved_cents"]:
        return (
            result
            | {
                "status": "BLOCKED",
                "reason_code": "CHARGE_EXCEEDS_RESERVATION",
                "reason": "Attributed charge exceeds the reservation; use manual reconciliation",
                "retry_when": "Review the charge and budget manually",
            }
            | _availability(budget)
        )
    proof = {
        "schema_version": "1.0",
        "method": method,
        "utc_day": day.date().isoformat(),
        "project_id": project,
        "exclusive_scope_declared": exclusive,
        "receipt_usage": target,
        "cohort_call_ids": [row["call_id"], *[r["call_id"] for r in peers]],
        "evidence": refs,
        "prior_evidence": prior_refs,
        "prior_billed_usd": str(prior),
        "billed_usd": str(usd),
        "eur_per_usd_ceiling": str(EUR_PER_USD_CEILING),
        "regional_multiplier": str(REGIONAL_CEILING),
        "tax_multiplier": str(TAX_CEILING),
        "unrounded_eur": str(eur),
        "rounding": "UP_TO_EUR_CENT",
        "accounted_cents": cents,
    }
    if not apply:
        return (
            result
            | {
                "status": "READY",
                "attribution": proof,
                "would_release_cents": row["reserved_cents"] - cents,
            }
            | _availability(budget)
        )
    if not budget.settle(call_id, cents, canonical(proof), expected_unknown=row["provenance"]):
        return reconcile(budget, call_id)
    return (
        result
        | {
            "status": "SETTLED",
            "ledger_status": "SETTLED",
            "actual_cents": cents,
            "released_now_cents": row["reserved_cents"] - cents,
            "attribution": proof,
        }
        | _availability(budget)
    )
