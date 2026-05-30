from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

import src.engine.audit_log as audit_log
from src.engine.audit_log import AuditEntry

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditRow(BaseModel):
    entry_id: str
    timestamp: str
    agent_id: str
    action_type: str
    parameters: str
    violations: str
    rationale: str
    outcome: str
    latency_ms: int


class ChainStatus(BaseModel):
    valid: bool
    entry_count: int
    broken_at: str | None = None


@router.get("/recent", response_model=list[AuditRow], summary="Recent audit entries")
async def recent(limit: int = Query(50, ge=1, le=500)) -> list[AuditRow]:
    entries: list[AuditEntry] = await audit_log.get_recent(limit=limit)
    return [
        AuditRow(
            entry_id=e.entry_id or "",
            timestamp=e.timestamp or "",
            agent_id=e.agent_id,
            action_type=e.action_type,
            parameters=e.parameters,
            violations=e.violations,
            rationale=e.rationale,
            outcome=e.outcome,
            latency_ms=e.latency_ms,
        )
        for e in entries
    ]


@router.get("/verify", response_model=ChainStatus, summary="Verify audit chain integrity")
async def verify() -> ChainStatus:
    result = await audit_log.verify_chain()
    return ChainStatus(
        valid=result.valid,
        entry_count=result.entry_count,
        broken_at=result.broken_at,
    )


@router.post("/reset", summary="Reset audit log (dev/demo only)")
async def reset() -> dict:
    """Drop and recreate the audit_entries table, starting a fresh chain.

    Intended for demo and development use only. In production this endpoint
    should be removed or protected behind authentication.
    """
    import aiosqlite
    db_path = audit_log.DB_PATH
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DROP TRIGGER IF EXISTS prevent_update")
        await db.execute("DROP TRIGGER IF EXISTS prevent_delete")
        await db.execute("DROP TABLE IF EXISTS audit_entries")
        await db.commit()
    await audit_log.init_db(db_path)
    logger.warning("Audit log reset — all entries deleted and chain restarted.")
    return {"reset": True}
