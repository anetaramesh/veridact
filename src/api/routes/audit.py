from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

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
