"""Read-only GitHub transport and transactional admission to the existing queue."""

import http.client
import json
import re
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator

from .audit_model import Budget
from .contracts import HypothesisManifest, Model, _unique, canonical, digest
from .implementation import Coordinator
from .implementation_contracts import ImplementationPlan
from .processes import coordinator_lock
from .readonly import ReadOnlyStore
from .store import Store, utc_now

REPO = "jogutierrez99/trading-lab"
LABEL = "strategy-intake"
MAX_BODY = 24_000
PAGE_SIZE = 30
MAX_PAGES = 5
CHECKPOINTS = """CREATE TABLE IF NOT EXISTS github_intake (
    issue_number INTEGER PRIMARY KEY, issue_id INTEGER NOT NULL UNIQUE,
    source_mode TEXT NOT NULL,
    author_id INTEGER, issue_url TEXT NOT NULL, body_sha256 TEXT,
    proposal_json TEXT, proposal_sha256 TEXT, identity TEXT, status TEXT NOT NULL,
    reason TEXT, task_id TEXT REFERENCES tasks(task_id), research_date TEXT,
    recorded_at_utc TEXT NOT NULL
)"""

BoundedText = Annotated[str, Field(min_length=1, max_length=2000)]


def normalized_source(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port is not None
        or parts.query
        or parts.fragment
        or not parts.path.strip("/")
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise ValueError(
            "Original source must be a canonical HTTPS URL without credentials, query or fragment"
        )
    path = parts.path.rstrip("/")
    if parts.hostname == "doi.org":
        path = path.casefold()
    return urlunsplit(("https", parts.hostname, path, "", ""))


class Proposal(Model):
    schema_version: Literal["1.0"]
    origin: Literal["chatgpt-daily-0900"]
    research_date: date
    source_url: Annotated[str, Field(max_length=2000)]
    evidence: BoundedText
    benchmark: BoundedText
    priority: Literal["LOW", "NORMAL", "HIGH"]
    manifest: HypothesisManifest

    _source = field_validator("source_url")(normalized_source)

    @model_validator(mode="after")
    def source_is_cited(self):
        if self.source_url not in {ref.reference for ref in self.manifest.source_refs}:
            raise ValueError("source_url must appear in manifest.source_refs")
        return self

    def identity(self) -> str:
        thesis = " ".join(
            unicodedata.normalize("NFKC", self.manifest.market_hypothesis).casefold().split()
        )
        return digest(canonical([self.source_url, thesis]))


def parse_proposal(body: str) -> Proposal:
    if len(body.encode("utf-8")) > MAX_BODY:
        raise ValueError("Issue body exceeds intake limit")
    match = re.fullmatch(r"```json\r?\n(.*?)\r?\n```", body.strip(), re.DOTALL)
    payload = json.loads(match[1] if match else body, object_pairs_hook=_unique)
    return Proposal.model_validate_json(canonical(payload))


class GitHubUnavailable(Exception):
    pass


def _page(token: str, page: int):
    query = urlencode(
        {
            "labels": LABEL,
            "state": "open",
            "sort": "created",
            "direction": "asc",
            "per_page": PAGE_SIZE,
            "page": page,
        }
    )
    return _get(token, f"/repos/{REPO}/issues?{query}")


def _get(token: str, path: str):
    conn = http.client.HTTPSConnection("api.github.com", timeout=8)
    try:
        conn.request(
            "GET",
            path,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "TradingLab-StrategyIntake",
            },
        )
        response = conn.getresponse()
        if response.status in (502, 503, 504) and not response.getheader("Retry-After"):
            raise TimeoutError("Transient GitHub response")
        if response.status != 200:
            raise GitHubUnavailable(f"GitHub HTTP {response.status}")
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise GitHubUnavailable("GitHub response exceeds the page limit")
        return json.loads(raw), 'rel="next"' in (response.getheader("Link") or "")
    finally:
        conn.close()


def _retry_read(read, *args):
    for attempt in range(2):
        try:
            return read(*args)
        except (OSError, http.client.HTTPException):
            if attempt:
                raise GitHubUnavailable("GitHub unavailable after two read attempts") from None
        except (ValueError, RecursionError):
            raise GitHubUnavailable("Invalid GitHub response") from None


def fetch_issue(token: str, number: int) -> list:
    if not 0 < number < 2**63:
        raise ValueError("GitHub issue number must be positive and fit in SQLite")
    issue, more = _retry_read(_get, token, f"/repos/{REPO}/issues/{number}")
    if not isinstance(issue, dict) or issue.get("number") != number or more:
        raise GitHubUnavailable("GitHub did not return the requested Issue")
    return [issue]


def fetch_issues(token: str) -> list:
    issues = []
    for page in range(1, MAX_PAGES + 1):
        batch, more = _retry_read(_page, token, page)
        if not isinstance(batch, list) or len(batch) > PAGE_SIZE:
            raise GitHubUnavailable("Unexpected GitHub page")
        issues.extend(batch)
        if not more:
            return issues
    raise GitHubUnavailable("Too many open intake issues; review and close handled issues first")


def _process(conn, store, issue, author_ids, source_mode):
    if not isinstance(issue, dict) or any(
        type(issue.get(k)) is not int or not 0 < issue[k] < 2**63 for k in ("id", "number")
    ):
        return {"status": "REJECTED", "reason": "Missing GitHub issue identity"}
    number = issue["number"]
    url = f"https://github.com/{REPO}/issues/{number}"
    body = issue.get("body")
    body_hash = digest(body) if isinstance(body, str) else None
    user = issue.get("user")
    author_id = user.get("id") if isinstance(user, dict) else None
    if type(author_id) is not int or not 0 < author_id < 2**63:
        author_id = None
    old = conn.execute(
        "SELECT * FROM github_intake WHERE issue_number=? OR issue_id=?",
        (number, issue["id"]),
    ).fetchone()
    if old:
        if (
            old["issue_number"],
            old["issue_id"],
            old["author_id"],
            old["body_sha256"],
            old["source_mode"],
        ) != (
            number,
            issue["id"],
            author_id,
            body_hash,
            source_mode,
        ):
            return {
                "status": "REJECTED_EDIT",
                "issue_number": number,
                "reason": "Issue differs from the original checkpoint",
            }
        return _result(old) | {"replayed": True}
    reason = None
    labels = issue.get("labels")
    if author_id not in author_ids:
        reason = "UNAUTHORIZED_AUTHOR"
    elif (
        issue.get("html_url") != url
        or issue.get("state") != "open"
        or "pull_request" in issue
        or not isinstance(labels, list)
        or not any(isinstance(label, dict) and label.get("name") == LABEL for label in labels)
    ):
        reason = "OUTSIDE_INTAKE_CHANNEL"
    proposal = None
    if reason is None:
        try:
            proposal = parse_proposal(body if isinstance(body, str) else "")
        except (ValueError, RecursionError):
            reason = "INVALID_PROPOSAL"
    identity = encoded = proposal_hash = task = day = None
    status = "REJECTED"
    if proposal is not None:
        identity = proposal.identity()
        encoded = canonical(proposal.model_dump(mode="json"))
        proposal_hash = digest(encoded)
        day = proposal.research_date.isoformat()
        duplicate = conn.execute(
            "SELECT task_id FROM github_intake WHERE identity=? AND task_id IS NOT NULL",
            (identity,),
        ).fetchone()
        submitted = conn.execute(
            "SELECT manifest_sha256 FROM submissions WHERE hypothesis_id=?",
            (proposal.manifest.hypothesis_id,),
        ).fetchone()
        if duplicate:
            status, task = "DUPLICATE", duplicate["task_id"]
        elif submitted and submitted["manifest_sha256"] != digest(proposal.manifest.snapshot()):
            reason = "HYPOTHESIS_ID_CONFLICT"
        elif (
            conn.execute(
                "SELECT count(*) FROM github_intake WHERE research_date=? AND status='ACCEPTED'",
                (day,),
            ).fetchone()[0]
            >= 3
        ):
            reason = "DAILY_LIMIT"
        else:
            registered = store._register(conn, proposal.manifest)
            task = registered["task_id"]
            status = "DUPLICATE" if registered["duplicate"] else "ACCEPTED"
    conn.execute(
        """INSERT INTO github_intake (
            issue_number, issue_id, source_mode, author_id, issue_url, body_sha256,
            proposal_json, proposal_sha256, identity, status, reason, task_id,
            research_date, recorded_at_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            number,
            issue["id"],
            source_mode,
            author_id,
            url,
            body_hash,
            encoded,
            proposal_hash,
            identity,
            status,
            reason,
            task,
            day,
            utc_now(),
        ),
    )
    return _result(
        conn.execute("SELECT * FROM github_intake WHERE issue_number=?", (number,)).fetchone()
    )


def _result(row):
    return {
        key: row[key]
        for key in (
            "issue_number",
            "issue_url",
            "source_mode",
            "status",
            "reason",
            "task_id",
            "proposal_sha256",
        )
    }


def consume(database: Path, author_ids: set[int], read_issues, *, source_mode: str) -> dict:
    if source_mode not in {"FIXTURE", "GITHUB"}:
        raise ValueError("Invalid intake source mode")
    if not author_ids or any(type(n) is not int or n <= 0 for n in author_ids):
        raise ValueError("Configure authorized numeric GitHub author IDs")
    database = database.resolve()
    with coordinator_lock(database.with_suffix(".github-intake.lock")):
        try:
            issues = read_issues()
        except GitHubUnavailable as exc:
            return {"status": "WAITING_GITHUB", "reason": str(exc), "issues": []}
        if not issues:
            return {"status": "NO_PROPOSALS", "issues": []}
        store = Store(database)
        results = []
        for issue in issues:
            with store.transaction() as conn:
                conn.execute(CHECKPOINTS)
                results.append(_process(conn, store, issue, author_ids, source_mode))
        return {"status": "CHECKED", "issues": results}


def prepare(
    database: Path,
    ledger: Path,
    number: int,
    reviewed_sha: str,
    repo: Path,
    artifacts: Path,
    plan: ImplementationPlan,
) -> dict:
    if database.resolve() == ledger.resolve():
        raise ValueError("Queue and canonical ledger must be separate")
    reader = ReadOnlyStore(database)
    with coordinator_lock(reader.path.with_suffix(".github-intake.lock")):
        with reader.connection() as conn:
            row = conn.execute(
                "SELECT * FROM github_intake WHERE issue_number=?", (number,)
            ).fetchone()
            if (
                not row
                or row["status"] != "ACCEPTED"
                or reviewed_sha != row["proposal_sha256"]
                or digest(row["proposal_json"]) != reviewed_sha
            ):
                raise ValueError(
                    "Preparation requires the accepted Issue and reviewed proposal hash"
                )
            proposal = Proposal.model_validate_json(row["proposal_json"])
            task = conn.execute(
                """SELECT manifest_sha256 FROM candidates JOIN tasks USING(candidate_id)
                WHERE task_id=?""",
                (row["task_id"],),
            ).fetchone()
            if not task or task["manifest_sha256"] != digest(proposal.manifest.snapshot()):
                raise ValueError("Queued manifest differs from reviewed proposal")
            attempt = conn.execute(
                "SELECT attempt_id,status FROM attempts WHERE task_id=? ORDER BY number DESC",
                (row["task_id"],),
            ).fetchone()
        if attempt:
            return {"status": "EXISTING_ATTEMPT", "attempt": dict(attempt)}
        try:
            available = Budget(ReadOnlyStore(ledger)).available()
            if available <= 0:
                raise ValueError("GLOBAL_API_BUDGET_EXHAUSTED")
        except (OSError, ValueError, sqlite3.Error) as exc:
            return {"status": "WAITING_BUDGET", "reason": str(exc)}
        return Coordinator(Store(database)).prepare(row["task_id"], repo, artifacts, plan)
