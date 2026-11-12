"""Pre-call OpenAI billing snapshots and conservative itemized differencing."""

import http.client
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .billing import (
    EvidenceUnavailable,
    _admin_rows,
    _hash,
    _ledger_usage,
    _number,
    _usage,
    admin_evidence,
)
from .workspaces import write_json

DAY_SECONDS = 86400
ZERO_CACHE_LINES = {"cached input", "cache writes", "cache writes - 12hr"}


def _day(timestamp):
    return int(timestamp.timestamp()) // DAY_SECONDS * DAY_SECONDS


def _snapshot(directory, start, organization, project):
    captured_from = datetime.now(UTC)
    raw = {}
    usage, costs, sources = admin_evidence(start, project, organization=organization, archive=raw)
    snapshot = {
        "schema_version": "1.0",
        "started_at_utc": captured_from.isoformat(),
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "scope": {"organization": organization, "project": project, "start": start},
        "sources": sources,
        "responses": raw,
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid4().hex + ".json")
    write_json(path, snapshot)
    ref = {"path": str(path), "sha256": _hash(path.read_bytes())}
    return snapshot, usage, costs, ref


def capture_baseline(budget, provider, maximum_cents):
    """Capture inside the existing dispatch lock, before reserving or sending."""
    scope = getattr(provider, "billing_scope", None)
    if scope is None:
        return {}
    if budget.available() < maximum_cents:
        raise ValueError("GLOBAL_API_BUDGET_EXHAUSTED")
    start = _day(datetime.now(UTC))
    path = budget.store.path
    directory = path.with_name(path.stem + "-billing-snapshots")
    try:
        snapshot, usage, costs, ref = _snapshot(directory, start, *scope)
        if _day(datetime.fromisoformat(snapshot["captured_at_utc"])) != start:
            raise EvidenceUnavailable("UTC day changed during baseline capture")
        actual = _usage(usage, scope[1])
        peers = [
            row
            for row in budget.inspect()["calls"]
            if row["provider"] == "openai"
            and _day(datetime.fromisoformat(row["created_at_utc"])) == start
        ]
        if actual != _usage(_ledger_usage(peers), None):
            raise EvidenceUnavailable("Billing baseline Usage does not match the settled cohort")
        _itemized(costs, actual)
    except (
        OSError,
        http.client.HTTPException,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        raise ValueError(
            "Billing baseline unavailable: "
            + (str(exc) if isinstance(exc, EvidenceUnavailable) else type(exc).__name__)
        ) from None
    return {"billing_baseline": ref}


def _itemized(costs, usage):
    """Require the entire scope to be accounted for by uncached Standard tokens."""
    if any(tier != "default" or field == "input_cached_tokens" for (_, tier), field in usage):
        raise EvidenceUnavailable("Snapshot attribution requires uncached Standard usage")
    expected = {
        (model, direction): usage[(model, "default"), direction + "_tokens"]
        for (model, _), field in usage
        if field == "num_model_requests"
        for direction in ("input", "output")
    }
    result = {}
    seen = set()
    for row in costs:
        if row.get("amount_currency") != "usd" or row.get("quantity_unit") != "tokens":
            raise EvidenceUnavailable("Costs must have USD line items with token quantities")
        model, _, direction = (row.get("line_item") or "").rpartition(", ")
        key = (model, direction)
        if key in seen:
            raise EvidenceUnavailable("Duplicate billing line item")
        seen.add(key)
        quantity = _number(row.get("quantity"))
        amount = _number(row.get("amount_value"))
        if (
            direction in ZERO_CACHE_LINES
            and quantity == amount == 0
            and (model, "input") in expected
        ):
            continue
        if key not in expected or quantity != expected[key] or bool(quantity) != bool(amount):
            raise EvidenceUnavailable(
                "Costs do not match Usage or include another charge",
                "COST_NOT_AVAILABLE"
                if key in expected and quantity < expected[key]
                else "ATTRIBUTION_UNCERTAIN",
            )
        result[key] = quantity, amount
    if any(quantity and key not in result for key, quantity in expected.items()):
        raise EvidenceUnavailable(
            "Costs have not published matching token quantities", "COST_NOT_AVAILABLE"
        )
    return result


def _delta(prior, current, model):
    amount = Decimal(0)
    for key in prior.keys() | current.keys():
        old_count, old_cost = prior.get(key, (0, Decimal(0)))
        new_count, new_cost = current.get(key, (0, Decimal(0)))
        if key[0] != model and (old_count, old_cost) != (new_count, new_cost):
            raise EvidenceUnavailable("Another model's billed lines changed")
        if (
            new_count < old_count
            or new_cost < old_cost
            or (old_count and old_cost * new_count != new_cost * old_count)
        ):
            raise EvidenceUnavailable("Billing rate or coverage changed between snapshots")
        amount += new_cost - old_cost
    if amount <= 0:
        raise EvidenceUnavailable(
            "No positive attributable billed difference", "COST_NOT_AVAILABLE"
        )
    return amount


def attribute_snapshot(row, start, project, target, others):
    ref = json.loads(row["provenance"]).get("billing_baseline")
    if not ref:
        raise EvidenceUnavailable("Call has no pre-dispatch billing snapshot", "BASELINE_MISSING")
    path = Path(ref["path"])
    raw = path.read_bytes()
    if _hash(raw) != ref["sha256"]:
        raise EvidenceUnavailable("Pre-dispatch billing snapshot hash changed")
    prior = json.loads(raw)
    scope = prior["scope"]
    before = datetime.fromisoformat(prior["started_at_utc"])
    captured = datetime.fromisoformat(prior["captured_at_utc"])
    dispatched = datetime.fromisoformat(row["created_at_utc"])
    if (
        prior["schema_version"] != "1.0"
        or scope["start"] != start
        or scope["project"] != project
        or not _day(before) == _day(captured) == start
        or not before <= captured <= dispatched
    ):
        raise EvidenceUnavailable("Pre-dispatch billing snapshot is out of scope")
    organization = scope["organization"]
    rows = {}
    for label in ("usage", "costs"):
        raw = prior["responses"][label].encode("utf-8")
        if _hash(raw) != prior["sources"][label]["sha256"]:
            raise EvidenceUnavailable("Pre-dispatch billing response hash changed")
        rows[label] = _admin_rows(raw, label, start, project, organization)
    old_usage = _usage(rows["usage"], project)
    if old_usage != _usage(others, None):
        raise EvidenceUnavailable("Pre-dispatch Usage does not match the settled cohort")
    old_costs = _itemized(rows["costs"], old_usage)
    current, usage, costs, current_ref = _snapshot(path.parent, start, organization, project)
    if any(
        current["sources"][k]["query"] != prior["sources"][k]["query"]
        or current["sources"][k]["source"] != prior["sources"][k]["source"]
        for k in rows
    ):
        raise EvidenceUnavailable("Billing filters changed between snapshots")
    actual = _usage(usage, project)
    if actual != _usage([target, *others], None):
        raise EvidenceUnavailable(
            "Usage does not match the sole expected new request",
            "USAGE_INCOMPLETE_OR_DIFFERENT_SCOPE"
            if actual == old_usage
            else "ATTRIBUTION_UNCERTAIN",
        )
    current_costs = _itemized(costs, actual)
    usd = _delta(old_costs, current_costs, target["model"])
    return (
        usd,
        sum((amount for _, amount in old_costs.values()), Decimal(0)),
        {
            **current["sources"],
            "snapshot": current_ref,
            "scope": scope,
        },
        {**prior["sources"], "snapshot": ref, "scope": scope},
    )
