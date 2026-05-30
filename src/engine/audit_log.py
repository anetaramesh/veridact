from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path("audit.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_hash       TEXT    NOT NULL,
    entry_hash      TEXT    NOT NULL,
    timestamp       TEXT    NOT NULL,
    agent_id        TEXT    NOT NULL,
    action_type     TEXT    NOT NULL,
    parameters_json TEXT    NOT NULL,
    outcome         TEXT    NOT NULL,
    violations_json TEXT    NOT NULL,
    latency_ms      REAL    NOT NULL
)
"""


def _compute_hash(
    prev_hash: str,
    timestamp: str,
    agent_id: str,
    action_type: str,
    parameters_json: str,
    outcome: str,
    violations_json: str,
    latency_ms: float,
) -> str:
    """Compute the SHA-256 hash for one audit entry.

    The hash covers every auditable field plus the previous entry's hash,
    forming a tamper-evident chain.

    Args:
        prev_hash: SHA-256 hash of the immediately preceding entry
                   (``"0" * 64`` for the genesis entry).
        timestamp: ISO-8601 UTC timestamp of this entry.
        agent_id: Identifier of the agent that initiated the request.
        action_type: Action the agent attempted.
        parameters_json: JSON-serialised request parameters.
        outcome: ``"approved"`` or ``"blocked"``.
        violations_json: JSON-serialised list of violation details.
        latency_ms: Rule-evaluation latency in milliseconds.

    Returns:
        Hex-encoded SHA-256 digest string (64 characters).
    """
    payload = "|".join([
        prev_hash, timestamp, agent_id, action_type,
        parameters_json, outcome, violations_json, str(latency_ms),
    ])
    return hashlib.sha256(payload.encode()).hexdigest()


async def init_db(db_path: Path = DB_PATH) -> None:
    """Create the audit_log table if it does not already exist.

    Safe to call multiple times (idempotent).

    Args:
        db_path: Filesystem path to the SQLite database file.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()
    logger.info("Audit DB initialised at %s", db_path)


async def append_entry(
    *,
    agent_id: str,
    action_type: str,
    parameters: dict[str, Any],
    outcome: str,
    violations: list[dict[str, Any]],
    latency_ms: float,
    db_path: Path = DB_PATH,
) -> str:
    """Append an immutable, hash-chained entry to the audit log.

    Entries are append-only; no UPDATE or DELETE operations are performed.
    Each entry's ``entry_hash`` covers all fields plus the previous
    entry's hash, enabling offline chain-integrity verification.

    Args:
        agent_id: Identifier of the agent that initiated the request.
        action_type: Action the agent attempted (e.g. ``"wire_transfer"``).
        parameters: Request parameters.  Must not contain secrets or raw
                    account numbers (enforced by caller convention).
        outcome: ``"approved"`` or ``"blocked"``.
        violations: List of violation detail dicts (may be empty).
        latency_ms: End-to-end rule evaluation latency.
        db_path: Path to the SQLite database file.

    Returns:
        Hex-encoded SHA-256 ``entry_hash`` of the newly written record.
    """
    parameters_json = json.dumps(parameters, sort_keys=True)
    violations_json = json.dumps(violations, sort_keys=True)
    timestamp = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()

        prev_hash: str = row["entry_hash"] if row else "0" * 64
        entry_hash = _compute_hash(
            prev_hash, timestamp, agent_id, action_type,
            parameters_json, outcome, violations_json, latency_ms,
        )

        await db.execute(
            """INSERT INTO audit_log
               (prev_hash, entry_hash, timestamp, agent_id, action_type,
                parameters_json, outcome, violations_json, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (prev_hash, entry_hash, timestamp, agent_id, action_type,
             parameters_json, outcome, violations_json, latency_ms),
        )
        await db.commit()

    logger.debug("Audit entry written: agent=%s outcome=%s hash=%s...", agent_id, outcome, entry_hash[:8])
    return entry_hash


async def get_entries(limit: int = 100, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Fetch the most recent audit log entries, newest first.

    Args:
        limit: Maximum number of entries to return (default 100).
        db_path: Path to the SQLite database file.

    Returns:
        List of row dicts ordered by ``id`` descending.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]
