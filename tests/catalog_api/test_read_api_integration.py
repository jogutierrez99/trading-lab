import json
import os
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from catalog_read_support import extra_experiment, make_catalogue

from trading_lab_catalog.models import Bundle, canonical, fingerprint
from trading_lab_catalog.read_api import CatalogReader
from trading_lab_catalog.store import Store


def test_single_snapshot_during_concurrent_ingestion(catalog, monkeypatch):
    store, bundle = catalog
    reader = CatalogReader(store.path)
    started, inserted, commit_allowed, finished = Event(), Event(), Event(), Event()
    original_event = Store._event
    original_summary = CatalogReader._summary

    def event(conn, kind, source, digest):
        original_event(conn, kind, source, digest)
        if source == "concurrent fixture" and kind == "INGESTED":
            inserted.set()
            assert commit_allowed.wait(5)

    monkeypatch.setattr(Store, "_event", staticmethod(event))

    def summary(snap, record):
        started.set()
        assert inserted.wait(5)
        commit_allowed.set()
        result = original_summary(snap, record)
        assert not finished.is_set()
        return result

    monkeypatch.setattr(CatalogReader, "_summary", staticmethod(summary))
    timing = {}

    def writer():
        assert started.wait(5)
        begin = time.perf_counter()
        store.ingest(Bundle(experiments=[extra_experiment(bundle, "e2")]), "concurrent fixture")
        timing["writer_seconds"] = time.perf_counter() - begin
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer)
        reader_begin = time.perf_counter()
        result = reader.get_strategy("s")
        timing["reader_seconds"] = time.perf_counter() - reader_begin
        future.result(timeout=10)
    assert result["status"] == "OK"
    assert result["items"][0]["experiment_count"] == 1
    assert reader.get_catalog_status()["items"][0]["counts"]["experiments"] == 2
    assert store.verify()["status"] == "OK"
    assert timing["writer_seconds"] >= 0
    if os.environ.get("TRADING_LAB_READ_API_REPORT_DIR"):
        target = Path(os.environ["TRADING_LAB_READ_API_REPORT_DIR"])
        target.mkdir(parents=True, exist_ok=True)
        (target / "concurrency.json").write_text(
            json.dumps(
                {
                    **timing,
                    "old_experiment_count_in_snapshot": 1,
                    "experiment_count_after_commit": 2,
                    "synchronization": "events; commit waits for read snapshot closure",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_new_event_invalidates_cursor(catalog):
    store, _ = catalog
    reader = CatalogReader(store.path)
    first = reader.list_versions("s", page_size=1)
    store.record_verification({"synthetic": True})
    assert (
        reader.list_versions("s", page_size=1, cursor=first["next_cursor"])["status"]
        == "CURSOR_INVALIDATED"
    )


def test_declarative_legacy_claim_not_upgraded(tmp_path):
    store, bundle = make_catalogue(tmp_path)
    old = bundle.runs[0].model_dump(mode="json")
    old["audit_status"] = "SOURCE_AUDITED"
    with store.connection(write=True) as c:
        trigger = c.execute("SELECT sql FROM sqlite_master WHERE name='runs_no_update'").fetchone()[
            0
        ]
        c.execute("DROP TRIGGER runs_no_update")
        c.execute(
            "UPDATE runs SET payload=?,sha256=? WHERE id='r'", (canonical(old), fingerprint(old))
        )
        c.execute(trigger)
    reader = CatalogReader(store.path)
    assert reader.get_evidence_summary("r")["items"][0]["audit_status"] == "UNVERIFIED"
    assert reader.list_case_results("r", {"audit_status": "SOURCE_AUDITED"})["items"] == []


def test_corruption_is_integrity_error_not_query_error(catalog):
    store, _ = catalog
    with store.connection(write=True) as c:
        trigger = c.execute(
            "SELECT sql FROM sqlite_master WHERE name='experiments_no_update'"
        ).fetchone()[0]
        c.execute("DROP TRIGGER experiments_no_update")
        c.execute("UPDATE experiments SET payload='{}' WHERE id='e'")
        c.execute(trigger)
    assert CatalogReader(store.path).search_experiments()["status"] == "INTEGRITY_ERROR"


def test_real_symlink_guard_if_available(tmp_path):
    store, _ = make_catalogue(tmp_path / "source")
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(store.path.parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(
            f"Symlink unavailable: errno={exc.errno}, winerror={exc.winerror}; "
            "no elevation attempted"
        )
    before = store.path.read_bytes()
    assert CatalogReader(linked / store.path.name).get_catalog_status()["status"] == "BLOCKED"
    assert store.path.read_bytes() == before


def test_ten_thousand_experiments_bounded_queries(tmp_path):
    store, bundle = make_catalogue(tmp_path)
    extra = [extra_experiment(bundle, "e" + str(i)) for i in range(2, 10002) if i != 50]
    start = time.perf_counter()
    store.ingest(Bundle(experiments=extra), "10000 synthetic definitions; no execution")
    seed_seconds = time.perf_counter() - start
    reader = CatalogReader(store.path, cursor_key=b"x" * 32)
    timings = {}
    peaks = {}
    results = {}
    operations = {
        "filtered_search": lambda: reader.search_experiments(
            {"parameters": {"window": 9999}}, page_size=10
        ),
        "first_page": lambda: reader.search_experiments(page_size=50),
        "versions": lambda: reader.list_versions("s"),
        "strategy_summary": lambda: reader.get_strategy("s"),
        "run_details": lambda: reader.get_run_details("r"),
        "case_results": lambda: reader.list_case_results("r"),
    }
    for name, operation in operations.items():
        tracemalloc.start()
        begin = time.perf_counter()
        data = operation()
        timings[name] = time.perf_counter() - begin
        peaks[name] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert data["status"] == "OK"
        results[name] = data["count"]
    assert results["filtered_search"] == 1 and results["first_page"] == 50
    begin = time.perf_counter()
    unlimited = store.records("experiments")
    timings["existing_unlimited_read"] = time.perf_counter() - begin
    assert len(unlimited) == 10000
    begin = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        parallel = list(pool.map(lambda _: reader.search_experiments(page_size=50), range(8)))
    timings["eight_queries_four_readers"] = time.perf_counter() - begin
    assert all(r["status"] == "OK" and r["count"] == 50 for r in parallel)
    report = {
        "experiments": 10000,
        "seed_seconds": seed_seconds,
        "seconds": timings,
        "python_peak_bytes": peaks,
        "page_counts": results,
        "historical_backtests": 0,
        "performance_thresholds_enforced": False,
        "environment": "SQLite temporary fixture; tracemalloc covers Python allocations only",
    }
    print("READ_API_BENCHMARK " + json.dumps(report, sort_keys=True))
    if os.environ.get("TRADING_LAB_READ_API_REPORT_DIR"):
        out = Path(os.environ["TRADING_LAB_READ_API_REPORT_DIR"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def test_orphan_is_rejected_even_if_inserted_with_fk_disabled(catalog):
    import sqlite3

    store, bundle = catalog
    record = bundle.experiments[0].model_dump(mode="json")
    record.update(id="orphan", version_id="missing")
    with sqlite3.connect(store.path) as c:
        c.execute(
            "INSERT INTO experiments(id,payload,sha256,registered_at_utc,version_id) "
            "VALUES(?,?,?,?,?)",
            (
                "orphan",
                canonical(record),
                fingerprint(record),
                "2026-01-01T00:00:00+00:00",
                "missing",
            ),
        )
    assert CatalogReader(store.path).search_experiments()["status"] == "INTEGRITY_ERROR"


def test_audit_unrelated_decisions_do_not_block_case_query(catalog):
    from datetime import UTC, datetime

    from trading_lab_catalog.models import Decision

    store, bundle = catalog
    decisions = [
        Decision(
            id="other-" + str(i),
            strategy_id="s",
            version_id="v2",
            run_id=None,
            category="RESEARCH",
            verdict="NO_DECISION",
            reasoning="unrelated version",
            limitations=[],
            decided_by="synthetic fixture",
            decided_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for i in range(201)
    ]
    store.ingest(Bundle(research_decisions=decisions), "synthetic audit")
    response = CatalogReader(store.path).list_case_results("r")
    assert response["status"] == "OK" and response["count"] == 2


def _audit_junction(link, target):
    import os
    import subprocess

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "New-Item -ItemType Junction -Path $env:TL_AUDIT_LINK -Target $env:TL_AUDIT_TARGET "
            "-ErrorAction Stop | Out-Null",
        ],
        env={**os.environ, "TL_AUDIT_LINK": str(link), "TL_AUDIT_TARGET": str(target)},
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, "Temporary junction creation failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows native path test")
@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_NATIVE_LINK_TESTS") != "1",
    reason="Native links denied here; explicit capable-environment opt-in required",
)
def test_audit_preexisting_junction_is_blocked(tmp_path):
    store, _ = make_catalogue(tmp_path / "source")
    link = tmp_path / "alias"
    _audit_junction(link, store.path.parent)
    before = store.path.read_bytes()
    assert CatalogReader(link / store.path.name).get_catalog_status()["status"] == "BLOCKED"
    assert store.path.read_bytes() == before


@pytest.mark.skipif(os.name != "nt", reason="Windows native path test")
@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_NATIVE_LINK_TESTS") != "1",
    reason="Native links denied here; explicit capable-environment opt-in required",
)
def test_audit_directory_swap_cannot_redirect_sqlite_open(tmp_path, monkeypatch):
    from trading_lab_catalog import store as store_module
    from trading_lab_catalog.models import Strategy

    a, _ = make_catalogue(tmp_path / "a")
    b, _ = make_catalogue(tmp_path / "b")
    b.ingest(
        Bundle(
            strategies=[
                Strategy(id="alternate", name="Alternate", description="synthetic", source="audit")
            ]
        ),
        "synthetic audit",
    )
    canary = tmp_path / "canary.txt"
    canary.write_text("unchanged", encoding="utf-8")
    hashes = (a.path.read_bytes(), b.path.read_bytes(), canary.read_bytes())
    original = store_module.sqlite3.connect
    redirected = []

    def connect(uri, *args, **kwargs):
        if (
            isinstance(uri, str)
            and uri.startswith("file:")
            and uri.endswith("?mode=ro")
            and not redirected
        ):
            try:
                a.path.parent.rename(tmp_path / "a" / "saved")
            except OSError as exc:
                redirected.append({"blocked": True, "winerror": exc.winerror})
            else:
                _audit_junction(a.path.parent, b.path.parent)
                redirected.append({"blocked": False})
        return original(uri, *args, **kwargs)

    monkeypatch.setattr(store_module.sqlite3, "connect", connect)
    result = CatalogReader(a.path).get_catalog_status()
    assert redirected and (redirected[0]["blocked"] or result["status"] == "BLOCKED")
    if result["status"] == "OK":
        assert result["items"][0]["counts"]["strategies"] == 2
    assert b.path.read_bytes() == hashes[1] and canary.read_bytes() == hashes[2]
    original_a = (
        (tmp_path / "a" / "saved" / a.path.name) if not redirected[0]["blocked"] else a.path
    )
    assert original_a.read_bytes() == hashes[0]


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_NATIVE_LINK_TESTS") != "1",
    reason="Native links denied here; explicit capable-environment opt-in required",
)
def test_audit_hardlink_database_alias_is_blocked(tmp_path):
    import os

    store, _ = make_catalogue(tmp_path / "source")
    alias = tmp_path / "alias"
    alias.mkdir()
    os.link(store.path, alias / store.path.name)
    before = store.path.read_bytes()
    assert CatalogReader(alias / store.path.name).get_catalog_status()["status"] == "BLOCKED"
    assert store.path.read_bytes() == before


@pytest.mark.skipif(os.name != "nt", reason="Native Windows read handle validation")
def test_audit_native_guard_uses_only_existing_read_handles(catalog, monkeypatch):
    from trading_lab_catalog.read_paths import pinned_catalogue
    from trading_lab_orchestration import study_storage_windows as native

    store, _ = catalog
    original = native._open_no_reparse
    observed = []

    def opened(path, access, share, disposition, **kwargs):
        observed.append((access, share, disposition))
        return original(path, access, share, disposition, **kwargs)

    monkeypatch.setattr(native, "_open_no_reparse", opened)
    before = store.path.read_bytes()
    with pinned_catalogue(store.path) as object_id:
        assert object_id[0] == "NTFS"
    assert observed
    assert all(
        access == native.READ and share == 3 and disposition == 1
        for access, share, disposition in observed
    )
    assert store.path.read_bytes() == before
    assert sorted(p.name for p in store.path.parent.iterdir()) == [store.path.name]


@pytest.mark.skipif(os.name != "nt", reason="Native Windows read handle validation")
def test_audit_native_handles_prevent_file_and_directory_rename(catalog):
    from trading_lab_catalog.read_paths import pinned_catalogue

    store, _ = catalog
    before = store.path.read_bytes()
    with pinned_catalogue(store.path):
        for source, target in [
            (store.path, store.path.with_name("renamed.sqlite3")),
            (store.path.parent, store.path.parent.with_name("renamed-directory")),
        ]:
            with pytest.raises(OSError) as error:
                source.rename(target)
            assert error.value.winerror in (5, 32)
    assert store.path.read_bytes() == before


def test_audit_path_guard_failure_is_not_a_permissive_fallback(reader, monkeypatch):
    from contextlib import contextmanager

    from trading_lab_catalog import read_api
    from trading_lab_catalog.read_models import ReadFailure

    @contextmanager
    def denied(path):
        raise ReadFailure("BLOCKED", "Synthetic guard denial")
        yield

    monkeypatch.setattr(read_api, "pinned_catalogue", denied)
    assert reader.get_strategy("s")["status"] == "BLOCKED"
