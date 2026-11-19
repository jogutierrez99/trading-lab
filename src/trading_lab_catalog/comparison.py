"""Comparability gates. Returns observations without automatic winners."""

from .models import canonical

REQUIRED = (
    "asset",
    "timeframe",
    "market_type",
    "direction",
    "period_start_utc",
    "period_end_utc",
    "segment",
    "scenario",
    "costs",
    "capital_initial",
    "capital_policy",
    "warmup_bars",
    "dataset_sha256",
    "experimental_protocol",
    "risk",
    "execution_assumptions",
    "engine",
    "engine_version",
    "kind",
)


def compare(rows):
    if len(rows) < 2:
        return {
            "status": "NOT_COMPARABLE",
            "reasons": ["Require at least two cases"],
            "cases": rows,
        }
    differences = [
        key
        for key in REQUIRED
        if len({canonical(r.get(key)) for r in rows}) != 1
        or any(r.get(key) in (None, "UNKNOWN", "", {}) for r in rows)
    ]
    if differences:
        status, reasons = "NOT_COMPARABLE", ["Different or unknown " + k for k in differences]
    else:
        reasons = []
        if any(r["holdout"] != "UNOBSERVED" for r in rows):
            reasons.append("Holdout consumed or unknown; retrospective evidence")
        if any(r["trades"] < 30 for r in rows):
            reasons.append("Small trade samples")
        if any(r["audit_status"] != "SOURCE_AUDITED" for r in rows):
            reasons.append("Evidence is not source-audited")
        if any(r["status"] != "COMPLETE" for r in rows):
            reasons.append("Incomplete technical execution")
        status = "COMPARABLE_WITH_LIMITATIONS" if reasons else "COMPARABLE"
    return {"status": status, "reasons": reasons, "cases": rows, "winner": None}
