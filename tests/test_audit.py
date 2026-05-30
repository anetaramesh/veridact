from __future__ import annotations

import aiosqlite
import pytest

import src.engine.audit_log as al
from src.engine.audit_log import AuditEntry, _compute_entry_hash


@pytest.fixture
async def fresh_db(tmp_path):
    db = tmp_path / "audit_test.db"
    original = al.DB_PATH
    al.DB_PATH = db
    await al.init_db(db)
    yield db
    al.DB_PATH = original


async def _write_n(db, n: int) -> list[str]:
    """Write *n* entries and return their entry_ids."""
    ids = []
    for i in range(n):
        eid = await al.write_entry(
            AuditEntry(
                agent_id=f"agent-{i}",
                action_type="wire_transfer",
                parameters=f'{{"amount": {i * 100}}}',
                context_hash="abc123",
                policy_set="finra_wire_threshold.yaml",
                violations="[]",
                rationale="All rules passed.",
                outcome="approved",
                latency_ms=i,
            ),
            db_path=db,
        )
        ids.append(eid)
    return ids


@pytest.mark.asyncio
async def test_chain_is_valid_after_10_entries(fresh_db):
    await _write_n(fresh_db, 10)
    result = await al.verify_chain(db_path=fresh_db)
    assert result.valid is True
    assert result.entry_count == 10
    assert result.broken_at is None


@pytest.mark.asyncio
async def test_chain_detects_tampering(fresh_db):
    await _write_n(fresh_db, 5)

    # Tamper: directly mutate a field in SQLite bypassing the trigger by
    # temporarily dropping it, then recreating it.
    async with aiosqlite.connect(fresh_db) as db:
        await db.execute("DROP TRIGGER IF EXISTS prevent_update")
        await db.execute(
            "UPDATE audit_entries SET outcome = 'hard_block' WHERE rowid = 2"
        )
        await db.commit()

    result = await al.verify_chain(db_path=fresh_db)
    assert result.valid is False
    assert result.broken_at is not None


@pytest.mark.asyncio
async def test_audit_log_is_append_only(fresh_db):
    await _write_n(fresh_db, 1)

    with pytest.raises(Exception, match="append-only"):
        async with aiosqlite.connect(fresh_db) as db:
            await db.execute(
                "UPDATE audit_entries SET outcome = 'tampered' WHERE rowid = 1"
            )
            await db.commit()


@pytest.mark.asyncio
async def test_entry_hash_is_deterministic(fresh_db):
    await al.write_entry(
        AuditEntry(
            agent_id="agent-x",
            action_type="payment",
            parameters='{"amount": 42}',
            context_hash="deadbeef",
            policy_set="finra_wire_threshold.yaml",
            violations='[{"violation_code": "CODE"}]',
            rationale="test",
            outcome="hard_block",
            latency_ms=3,
        ),
        db_path=fresh_db,
    )

    entries = await al.get_recent(limit=1, db_path=fresh_db)
    e = entries[0]

    recomputed = _compute_entry_hash(
        e.entry_id, e.prev_hash, e.timestamp,
        e.agent_id, e.action_type, e.parameters, e.outcome,
    )
    assert recomputed == e.entry_hash
