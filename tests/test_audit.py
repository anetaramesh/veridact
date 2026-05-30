from __future__ import annotations
import hashlib
import json
import pytest
from pathlib import Path
import src.engine.audit_log as al


@pytest.fixture
async def fresh_db(tmp_path):
    db = tmp_path / "audit_test.db"
    original = al.DB_PATH
    al.DB_PATH = db
    await al.init_db(db)
    yield db
    al.DB_PATH = original


@pytest.mark.asyncio
async def test_first_entry_prev_hash_is_genesis(fresh_db):
    await al.append_entry(
        agent_id="a1", action_type="wire_transfer",
        parameters={"amount": 100}, outcome="approved",
        violations=[], latency_ms=5.0, db_path=fresh_db,
    )
    entries = await al.get_entries(db_path=fresh_db)
    assert entries[0]["prev_hash"] == "0" * 64


@pytest.mark.asyncio
async def test_chain_integrity(fresh_db):
    """Each entry's prev_hash must equal the previous entry's entry_hash."""
    for i in range(3):
        await al.append_entry(
            agent_id=f"agent-{i}", action_type="wire_transfer",
            parameters={"amount": i * 100}, outcome="approved",
            violations=[], latency_ms=1.0, db_path=fresh_db,
        )
    entries = await al.get_entries(db_path=fresh_db)
    # get_entries returns newest-first; reverse for chronological order
    entries = list(reversed(entries))
    for i in range(1, len(entries)):
        assert entries[i]["prev_hash"] == entries[i - 1]["entry_hash"], (
            f"Chain broken at entry {i}"
        )


@pytest.mark.asyncio
async def test_entry_hash_is_deterministic(fresh_db):
    """Recomputing the hash from stored fields must match the stored entry_hash."""
    await al.append_entry(
        agent_id="agent-x", action_type="payment",
        parameters={"amount": 42}, outcome="blocked",
        violations=[{"rule_id": "r1", "violation_code": "CODE", "rationale": "test"}],
        latency_ms=3.14, db_path=fresh_db,
    )
    entries = await al.get_entries(db_path=fresh_db)
    e = entries[0]
    recomputed = al._compute_hash(
        e["prev_hash"], e["timestamp"], e["agent_id"], e["action_type"],
        e["parameters_json"], e["outcome"], e["violations_json"], e["latency_ms"],
    )
    assert recomputed == e["entry_hash"]


@pytest.mark.asyncio
async def test_append_entry_persists_and_is_readable(fresh_db):
    """append_entry writes a record that get_entries can read back."""
    before = await al.get_entries(db_path=fresh_db)
    await al.append_entry(
        agent_id="api-sim",
        action_type="wire_transfer",
        parameters={"amount": 10},
        outcome="approved",
        violations=[],
        latency_ms=7.5,
        db_path=fresh_db,
    )
    after = await al.get_entries(db_path=fresh_db)
    assert len(after) == len(before) + 1
    assert after[0]["agent_id"] == "api-sim"
    assert after[0]["outcome"] == "approved"
