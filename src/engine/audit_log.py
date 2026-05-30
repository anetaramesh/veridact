from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DB_PATH = Path("audit.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_entries (
    entry_id     TEXT PRIMARY KEY,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    action_type  TEXT NOT NULL,
    parameters   TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    policy_set   TEXT NOT NULL,
    violations   TEXT NOT NULL,
    rationale    TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    latency_ms   INTEGER NOT NULL
)
"""

# Append-only enforcement: any UPDATE or DELETE raises a hard error.
_CREATE_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS prevent_update
BEFORE UPDATE ON audit_entries
BEGIN
    SELECT RAISE(FAIL, 'audit_entries is append-only: UPDATE is not permitted');
END
"""

_CREATE_TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS prevent_delete
BEFORE DELETE ON audit_entries
BEGIN
    SELECT RAISE(FAIL, 'audit_entries is append-only: DELETE is not permitted');
END
"""


class AuditEntry(BaseModel):
    """One immutable record in the SHA-256 hash-chained audit log.

    Fields populated by the caller (required before calling write_entry):
        agent_id, action_type, parameters, context_hash, policy_set,
        violations, rationale, outcome, latency_ms.

    Fields populated by write_entry:
        entry_id, prev_hash, entry_hash, timestamp.
    """

    entry_id: str = Field(default="")
    prev_hash: str = Field(default="")
    entry_hash: str = Field(default="")
    timestamp: str = Field(default="")
    agent_id: str
    action_type: str
    parameters: str  # JSON string — no raw account numbers
    context_hash: str  # SHA-256 of context, not the context itself
    policy_set: str  # which YAML files were active
    violations: str  # JSON array
    rationale: str
    outcome: str  # approved | hard_block | soft_hold | flagged
    latency_ms: int


class ChainVerificationResult(BaseModel):
    """Result of a full chain integrity walk.

    Attributes:
        valid: True when every entry_hash and every prev_hash link are correct.
        entry_count: Total number of entries inspected.
        broken_at: entry_id of the first entry where the chain is broken, or None.
    """

    valid: bool
    entry_count: int
    broken_at: Optional[str] = None


def _compute_entry_hash(
    entry_id: str,
    prev_hash: str,
    timestamp: str,
    agent_id: str,
    action_type: str,
    parameters: str,
    outcome: str,
) -> str:
    """SHA-256(entry_id + prev_hash + timestamp + agent_id + action_type + parameters + outcome)."""
    payload = entry_id + prev_hash + timestamp + agent_id + action_type + parameters + outcome
    return hashlib.sha256(payload.encode()).hexdigest()


def compute_context_hash(context: dict | str) -> str:
    """Return SHA-256 of the canonical JSON representation of *context*."""
    if isinstance(context, str):
        serialised = context
    else:
        serialised = json.dumps(context, sort_keys=True)
    return hashlib.sha256(serialised.encode()).hexdigest()


async def init_db(db_path: Path = DB_PATH) -> None:
    """Create the audit_entries table and append-only triggers if they do not exist.

    Safe to call multiple times (idempotent).

    Args:
        db_path: Filesystem path to the SQLite database file.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_TABLE)
        await db.execute(_CREATE_TRIGGER_UPDATE)
        await db.execute(_CREATE_TRIGGER_DELETE)
        await db.commit()
    logger.info("Audit DB initialised at %s", db_path)


async def write_entry(entry: AuditEntry, db_path: Path = DB_PATH) -> str:
    """Append an immutable, hash-chained entry and return its entry_id.

    The entry_id and timestamp are generated here if not already set.
    The prev_hash and entry_hash are always computed here — callers must
    not set them.

    Args:
        entry: Audit entry with all caller-supplied fields populated.
        db_path: Path to the SQLite database file.

    Returns:
        The entry_id (UUID) of the newly written record.

    Raises:
        aiosqlite.OperationalError: If the database trigger rejects the write
            (should never happen for INSERT, only for UPDATE/DELETE).
    """
    entry_id = entry.entry_id or str(uuid.uuid4())
    timestamp = entry.timestamp or datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT entry_hash FROM audit_entries ORDER BY timestamp DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()

        prev_hash = row["entry_hash"] if row else "GENESIS"
        entry_hash = _compute_entry_hash(
            entry_id, prev_hash, timestamp,
            entry.agent_id, entry.action_type, entry.parameters, entry.outcome,
        )

        await db.execute(
            """INSERT INTO audit_entries
               (entry_id, prev_hash, entry_hash, timestamp, agent_id, action_type,
                parameters, context_hash, policy_set, violations, rationale, outcome, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id, prev_hash, entry_hash, timestamp,
                entry.agent_id, entry.action_type, entry.parameters,
                entry.context_hash, entry.policy_set, entry.violations,
                entry.rationale, entry.outcome, entry.latency_ms,
            ),
        )
        await db.commit()

    logger.debug(
        "Audit entry written: entry_id=%s agent=%s outcome=%s hash=%.8s",
        entry_id, entry.agent_id, entry.outcome, entry_hash,
    )
    return entry_id


async def get_recent(limit: int = 100, db_path: Path = DB_PATH) -> list[AuditEntry]:
    """Return the most recent audit entries, newest first.

    Args:
        limit: Maximum number of entries to return.
        db_path: Path to the SQLite database file.

    Returns:
        List of :class:`AuditEntry` ordered by timestamp descending.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM audit_entries ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
    return [AuditEntry(**dict(r)) for r in rows]


async def verify_chain(db_path: Path = DB_PATH) -> ChainVerificationResult:
    """Walk all entries in chronological order and verify the hash chain.

    For each entry, recomputes entry_hash from its fields and checks that the
    next entry's prev_hash matches.  The genesis entry must have prev_hash
    equal to "GENESIS".

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        :class:`ChainVerificationResult` with valid=True if the chain is intact,
        or valid=False with broken_at set to the entry_id of the first bad entry.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM audit_entries ORDER BY timestamp ASC"
        ) as cursor:
            rows = await cursor.fetchall()

    entries = [dict(r) for r in rows]
    if not entries:
        return ChainVerificationResult(valid=True, entry_count=0)

    # Genesis entry must declare itself as such.
    if entries[0]["prev_hash"] != "GENESIS":
        return ChainVerificationResult(
            valid=False, entry_count=len(entries), broken_at=entries[0]["entry_id"]
        )

    for i, e in enumerate(entries):
        expected = _compute_entry_hash(
            e["entry_id"], e["prev_hash"], e["timestamp"],
            e["agent_id"], e["action_type"], e["parameters"], e["outcome"],
        )
        if expected != e["entry_hash"]:
            return ChainVerificationResult(
                valid=False, entry_count=len(entries), broken_at=e["entry_id"]
            )

        if i + 1 < len(entries) and entries[i + 1]["prev_hash"] != e["entry_hash"]:
            return ChainVerificationResult(
                valid=False, entry_count=len(entries), broken_at=entries[i + 1]["entry_id"]
            )

    return ChainVerificationResult(valid=True, entry_count=len(entries))
