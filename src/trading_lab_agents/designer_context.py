"""Designer-only catalogue capture. No economics, SQL, Store or execution tools."""

from pathlib import Path

from trading_lab_catalog.read_api import CatalogReader
from trading_lab_catalog.read_models import public_data
from trading_lab_orchestration.contracts import canonical

from .context import ContextLimits, ResearchError
from .models import ResearchRequest


class DesignerContext:
    def __init__(self, path: Path, *, fixture_root: Path, limits: ContextLimits | None = None):
        root, path = Path(fixture_root).absolute(), Path(path).absolute()
        if (
            ".." in path.parts
            or ".." in root.parts
            or not path.is_relative_to(root)
            or path == root
        ):
            raise ValueError("Explicit disposable catalogue root required")
        self._profile = CatalogReader(path).for_profile("designer")
        self.limits = ContextLimits.model_validate((limits or ContextLimits()).model_dump())

    def capture(self, request: ResearchRequest, *, version_ids: tuple[str, ...] = ()) -> dict:
        metrics = {"queries": 0, "pages": 0}
        for attempt in range(1, 4):
            try:
                result = self._capture(request, version_ids, metrics)
                result["metrics"] = {**metrics, "captures": attempt}
                return result
            except ResearchError as exc:
                if exc.code != "CURSOR_INVALIDATED" or attempt == 3:
                    raise
        raise AssertionError("Unreachable")

    def _capture(self, request, version_ids, metrics):
        checkpoint, stored = None, {}
        responses = []
        fields = {"id", "name", "family", "declared_family", "family_status", "version_count"}

        def query(operation, **args):
            nonlocal checkpoint
            if metrics["queries"] >= self.limits.max_queries:
                raise ResearchError("CONTEXT_QUERY_LIMIT")
            metrics["queries"] += 1
            result = self._profile.query(operation, **args)
            if result.get("status") != "OK":
                code = result.get("status")
                raise ResearchError(
                    code
                    if code
                    in {
                        "CURSOR_INVALIDATED",
                        "INVALID_CURSOR",
                        "NOT_FOUND",
                        "BLOCKED",
                        "INTEGRITY_ERROR",
                        "RESPONSE_LIMIT_EXCEEDED",
                    }
                    else "CATALOGUE_INVALID"
                )
            current = result.get("checkpoint")
            if not isinstance(current, str) or len(current) != 64:
                raise ResearchError("CATALOGUE_INVALID")
            if checkpoint is not None and current != checkpoint:
                raise ResearchError("CURSOR_INVALIDATED")
            checkpoint = current
            return result

        def pages(operation, **args):
            rows, cursor, seen = [], None, set()
            for _ in range(self.limits.max_pages):
                result = query(
                    operation, **args, page_size=self.limits.page_size, cursor=cursor, sort="id"
                )
                metrics["pages"] += 1
                items = result["items"]
                if operation in {"list_strategies", "get_strategy"}:
                    items = [{k: v for k, v in row.items() if k in fields} for row in items]
                for row in items:
                    key = (operation, row["id"])
                    if key in stored and stored[key] != row:
                        raise ResearchError("EVIDENCE_CONFLICT")
                    stored[key] = row
                rows.extend(items)
                responses.append(
                    {"operation": operation, "items": items, "query_id": result["query_id"]}
                )
                if len(canonical(responses).encode()) > self.limits.max_bytes:
                    raise ResearchError("CONTEXT_LIMIT_EXCEEDED")
                cursor = result.get("next_cursor")
                if cursor is None:
                    return rows
                if cursor in seen:
                    raise ResearchError("INVALID_CURSOR")
                seen.add(cursor)
            raise ResearchError("CONTEXT_PAGE_LIMIT")

        inventory = pages("list_strategies")
        criteria = {
            "asset": request.market.asset,
            "market_type": request.market.market_type,
            "timeframe": request.market.timeframe,
        }
        experiments = pages("search_experiments", filters=criteria)
        for ref in request.catalog_context:
            if ref.entity_type == "experiment":
                experiments.extend(
                    pages("search_experiments", filters={"experiment_id": ref.entity_id})
                )
        unique = {}
        for row in experiments:
            if any(row[k] != v for k, v in criteria.items()):
                raise ResearchError("REFERENCE_MARKET_MISMATCH")
            if row["id"] in unique and unique[row["id"]] != row:
                raise ResearchError("EVIDENCE_CONFLICT")
            unique[row["id"]] = row
        experiments = [unique[k] for k in sorted(unique)]
        requested_versions = (
            set(version_ids)
            | {r.entity_id for r in request.catalog_context if r.entity_type == "version"}
            | {e["version_id"] for e in experiments}
        )
        relevant = {r.entity_id for r in request.catalog_context if r.entity_type == "strategy"}
        # Resolve explicit version IDs without broadening access to other profiles.
        versions = []
        for strategy in inventory:
            if strategy["id"] in relevant or requested_versions:
                rows = pages("list_versions", strategy_id=strategy["id"])
                selected = [
                    v for v in rows if v["id"] in requested_versions or strategy["id"] in relevant
                ]
                versions.extend(selected)
                requested_versions -= {v["id"] for v in selected}
        if requested_versions or not relevant <= {s["id"] for s in inventory}:
            raise ResearchError("NOT_FOUND")
        result = {
            "checkpoint": checkpoint,
            "inventory_scope": "DISCOVERY_ONLY_NOT_EQUIVALENCE",
            "inventory": inventory,
            "versions": versions,
            "experiments": experiments,
            "responses": responses,
        }
        # Do not return non-selected version rows from the internal resolution pages.
        result.pop("responses")
        if public_data(result) != result:
            raise ResearchError("PRIVATE_PROVIDER_CONTEXT")
        if len(canonical(result).encode()) > self.limits.max_bytes:
            raise ResearchError("CONTEXT_LIMIT_EXCEEDED")
        return result
