import copy

import pytest

from trading_lab_agents import CatalogContext, FakeProvider, SourceDocument
from trading_lab_agents.context import ContextLimits
from trading_lab_agents.models import ResearchRequest
from trading_lab_catalog.read_api import CatalogReader
from trading_lab_orchestration.contracts import canonical


def test_r12_valid_pagination_has_no_duplicates(
    catalogue, tmp_path, request_data, documents, exercise
):
    context = CatalogContext(
        catalogue[0].path, fixture_root=tmp_path, limits=ContextLimits(page_size=1)
    )
    result, *_ = exercise(FakeProvider(), request_data(), documents, context=context)
    assert result["status"] == "COMPLETE", result
    strategies = [
        row["id"]
        for response in result["antecedents"]["responses"]
        if response["operation"] == "list_strategies"
        for row in response["items"]
    ]
    assert strategies == ["empty", "s"]
    assert "next_cursor" not in canonical(result["antecedents"])


@pytest.mark.parametrize("code,retried", [("INVALID_CURSOR", False), ("CURSOR_INVALIDATED", True)])
def test_r12_cursor_error_recaptures_only_reading(
    catalogue, tmp_path, request_data, documents, exercise, code, retried, monkeypatch
):
    context = CatalogContext(
        catalogue[0].path, fixture_root=tmp_path, limits=ContextLimits(page_size=1)
    )
    original = context._profile.query
    injected = False

    def query(operation, **arguments):
        nonlocal injected
        if arguments.get("cursor") is not None and not injected:
            injected = True
            return {"status": code}
        return original(operation, **arguments)

    monkeypatch.setattr(context._profile, "query", query)
    provider = FakeProvider()
    result, *_ = exercise(provider, request_data(), documents, context=context)
    assert injected
    if retried:
        assert result["status"] == "COMPLETE" and result["receipt"]["captures"] == 2, result
        assert provider.calls == 1
    else:
        assert result["error_code"] == "INVALID_CURSOR" and provider.calls == 0


def test_r12_inconsistent_snapshots_block_before_provider(
    catalogue, tmp_path, request_data, documents, exercise, monkeypatch
):
    context = CatalogContext(catalogue[0].path, fixture_root=tmp_path)
    original, calls = context._profile.query, []

    def query(operation, **arguments):
        result = original(operation, **arguments)
        calls.append(operation)
        if operation == "find_existing_research":
            result["checkpoint"] = "a" * 64
        return result

    monkeypatch.setattr(context._profile, "query", query)
    provider = FakeProvider()
    result, *_ = exercise(provider, request_data(), documents, context=context)
    assert result["error_code"] == "CURSOR_INVALIDATED" and provider.calls == 0
    assert calls.count("list_strategies") == 3  # Initial capture + two additional captures.


def test_r12_oversized_page_and_query_limits(
    catalogue, tmp_path, request_data, documents, exercise
):
    with pytest.raises(ValueError):
        ContextLimits(page_size=201)
    with pytest.raises(ValueError):
        ContextLimits(page_size=True)
    context = CatalogContext(
        catalogue[0].path, fixture_root=tmp_path, limits=ContextLimits(page_size=1, max_pages=1)
    )
    provider = FakeProvider()
    result, *_ = exercise(provider, request_data(), documents, context=context)
    assert result["error_code"] == "CONTEXT_PAGE_LIMIT" and provider.calls == 0
    context = CatalogContext(
        catalogue[0].path, fixture_root=tmp_path, limits=ContextLimits(max_queries=1)
    )
    result, *_ = exercise(provider, request_data(request_id="queries"), documents, context=context)
    assert result["error_code"] == "CONTEXT_QUERY_LIMIT" and provider.calls == 0


def test_only_researcher_profile_methods_are_used(
    catalogue, tmp_path, request_data, documents, exercise, monkeypatch
):
    from trading_lab_catalog.read_api import PROFILES

    context = CatalogContext(catalogue[0].path, fixture_root=tmp_path)
    original, calls = context._profile.query, []

    def query(operation, **arguments):
        calls.append(operation)
        assert operation in PROFILES["researcher"]
        return original(operation, **arguments)

    monkeypatch.setattr(context._profile, "query", query)
    result, *_ = exercise(FakeProvider(), request_data(), documents, context=context)
    assert result["status"] == "COMPLETE", result
    assert set(calls) <= set(PROFILES["researcher"])
    assert original("compare_results", case_ids=[])["status"] == "INVALID_QUERY"


@pytest.mark.parametrize(
    "entity,identifier",
    [
        ("strategy", "missing"),
        ("experiment", "missing"),
        ("run", "missing"),
        ("artifact", "missing"),
    ],
)
def test_unknown_request_references_fail_closed(
    entity, identifier, exercise, request_data, documents
):
    data = request_data(
        catalog_context=[
            {
                "entity_type": entity,
                "entity_id": identifier,
                "record_fingerprint": None,
                "checkpoint": None,
                "effective_status": "UNKNOWN",
            }
        ]
    )
    provider = FakeProvider()
    result, *_ = exercise(provider, data, documents)
    assert result["status"] == "BLOCKED" and provider.calls == 0
    assert result["error_code"] in {"NOT_FOUND", "INVENTED_REFERENCE"}


def test_catalogue_reference_claim_cannot_be_upgraded(exercise, request_data, documents):
    data = request_data(
        catalog_context=[
            {
                "entity_type": "strategy",
                "entity_id": "s",
                "record_fingerprint": None,
                "checkpoint": None,
                "effective_status": "SOURCE_AUDITED",
            }
        ]
    )
    provider = FakeProvider()
    result, *_ = exercise(provider, data, documents)
    assert result["error_code"] == "REFERENCE_MISMATCH" and provider.calls == 0


def test_catalogue_cannot_escape_explicit_fixture_root(tmp_path):
    with pytest.raises(ValueError):
        CatalogContext(tmp_path.parent / "outside.sqlite3", fixture_root=tmp_path)


@pytest.mark.parametrize("location", ["objective", "source"])
def test_private_input_blocked_before_provider(exercise, request_data, documents, location):
    data = request_data()
    docs = documents
    if location == "objective":
        data["objective"] = "Read C:/Users/private/secret.txt"
    else:
        from trading_lab_catalog.verification import sha

        docs = (
            SourceDocument(
                reference_id="source_01",
                kind=documents[0].kind,
                content=b"Bearer private-credential",
            ),
        )
        data["source_refs"][0]["sha256"] = sha(docs[0].content)
    provider = FakeProvider()
    result, *_ = exercise(provider, data, docs)
    assert result["status"] == "BLOCKED" and provider.calls == 0
    assert "private-credential" not in canonical(result)


@pytest.mark.parametrize(
    "mutation",
    [
        "invented_catalogue",
        "changed_accreditation",
        "changed_checkpoint",
        "changed_market",
        "request_id",
        "dropped_limitation",
        "invented_metric",
    ],
)
def test_output_reference_and_semantic_guards(exercise, request_data, documents, mutation):
    good, *_ = exercise(FakeProvider(), request_data(), documents)
    assert good["status"] == "COMPLETE", good
    payload = copy.deepcopy(good["hypothesis"])
    payload["request_id"] = "output_guard"
    candidate = payload["candidates"][0]
    if mutation == "invented_catalogue":
        candidate["catalog_refs"][0]["entity_id"] = "invented"
    elif mutation == "changed_accreditation":
        candidate["catalog_refs"][0]["effective_status"] = "SOURCE_AUDITED"
    elif mutation == "changed_checkpoint":
        candidate["catalog_refs"][0]["checkpoint"] = "f" * 64
    elif mutation == "changed_market":
        candidate["asset"] = "ETHUSDT"
    elif mutation == "request_id":
        payload["request_id"] = "wrong"
    elif mutation == "dropped_limitation":
        candidate["limitations"] = ["Pretend nothing is uncertain"]
    else:
        candidate["net_return_pct"] = 100
    provider = FakeProvider(response=canonical(payload).encode())
    result, *_ = exercise(provider, request_data(request_id="output_guard"), documents)
    assert result["status"] == "BLOCKED" and provider.calls == 1


@pytest.mark.parametrize(
    "raw",
    [
        b'{"status":"NO_HYPOTHESIS","status":"APPROVED"}',
        b'{"notes":NaN}',
        b'{"notes":1e400}',
        b" " * (32 * 1024 + 1),
    ],
    ids=["duplicate", "nan", "overflow", "oversized"],
)
def test_raw_response_invalid_and_bounded(exercise, request_data, documents, raw):
    result, *_ = exercise(FakeProvider(response=raw), request_data(), documents)
    assert result["status"] == "BLOCKED" and result["error_code"] == "CONTRACT_INVALID"


def test_simulator_has_no_keys_clients_or_env_requirement(
    exercise, request_data, documents, monkeypatch
):
    import builtins

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    original = builtins.open

    def guarded(file, *args, **kwargs):
        assert not str(file).endswith(".env")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    provider = FakeProvider()
    result, *_ = exercise(provider, request_data(), documents)
    assert result["status"] == "COMPLETE", result
    assert provider.calls == 1


def test_repeat_does_not_requery_changed_catalogue(exercise, request_data, documents, monkeypatch):
    provider = FakeProvider()
    result, agent, context, _ = exercise(provider, request_data(), documents)

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must use its frozen receipt before catalogue lookup")

    monkeypatch.setattr(context, "capture", forbidden)
    assert agent.run(canonical(request_data()).encode(), documents=documents) == result
    assert provider.calls == 1


def test_real_api_rejects_bad_cursor_without_writing(catalogue):
    response = (
        CatalogReader(catalogue[0].path)
        .for_profile("researcher")
        .query("list_strategies", page_size=1, cursor="malformed")
    )
    assert response["status"] == "INVALID_CURSOR"


def test_context_has_one_checkpoint(catalogue, tmp_path, request_data):
    context = CatalogContext(catalogue[0].path, fixture_root=tmp_path)
    capture = context.capture(ResearchRequest.model_validate(request_data()))
    assert {r.checkpoint for r in capture.references} == {capture.checkpoint}


def test_no_direct_operational_or_network_imports():
    import ast
    from pathlib import Path

    root = Path(__file__).parents[2] / "src/trading_lab_agents"
    imports = set()
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    assert not any(
        name.split(".")[0]
        in {"openai", "requests", "httpx", "urllib", "socket", "subprocess", "dotenv"}
        for name in imports
    )
    assert {name for name in imports if name.startswith("trading_lab_orchestration")} == {
        "trading_lab_orchestration.contracts"
    }


@pytest.mark.parametrize("claim", ["UNKNOWN", "UNANCHORED_HASH"])
def test_missing_source_anchor_never_becomes_verified(exercise, request_data, documents, claim):
    from trading_lab_catalog.verification import parse

    data = request_data()
    data["source_refs"][0]["sha256"] = None
    if claim == "UNANCHORED_HASH":
        data["source_refs"][0]["verification"] = "HASH_VERIFIED"
    result, _, _, book = exercise(FakeProvider(), data, documents)
    if claim == "UNKNOWN":
        assert result["status"] == "COMPLETE", result
        packet = parse(bytes.fromhex(book.export("req_01")["context_hex"]))
        assert packet["documents"][0]["verification"] == "UNVERIFIED"
    else:
        assert result["error_code"] == "SOURCE_HASH_MISSING"
