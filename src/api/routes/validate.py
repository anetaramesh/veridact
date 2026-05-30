from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.engine.audit_log import append_entry
from src.rules.models import RuleResult

logger = logging.getLogger(__name__)
router = APIRouter()


class ValidateRequest(BaseModel):
    """Inbound validation request from an AI agent.

    Attributes:
        action_type: Category of action the agent is attempting (e.g. ``"wire_transfer"``).
        parameters: Action-specific payload fields used by rule evaluators.
        context: Ambient metadata (session info, account metadata) available to rules.
        agent_id: Identifier of the requesting agent — recorded in the audit log.
    """

    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    agent_id: str


class ViolationDetail(BaseModel):
    """Details of a single rule violation.

    Attributes:
        rule_id: ID of the rule that was violated.
        violation_code: Short machine-readable code (e.g. ``OFAC_SANCTIONS_MATCH``).
        rationale: Human-readable explanation suitable for audit reports.
    """

    rule_id: str
    violation_code: str
    rationale: str


class ValidateResponse(BaseModel):
    """Validation outcome returned to the calling agent.

    Attributes:
        approved: ``True`` if all rules passed; ``False`` if any rule blocked.
        violations: List of rule violations (empty when ``approved`` is ``True``).
        rationale: Summary rationale covering all violations.
        latency_ms: Total validation latency in milliseconds.
        request_id: UUID for correlating this response with audit log entries.
    """

    approved: bool
    violations: list[ViolationDetail]
    rationale: str
    latency_ms: float
    request_id: str


@router.post("/validate", response_model=ValidateResponse, summary="Validate an agent action")
async def validate(req: ValidateRequest, request: Request) -> ValidateResponse:
    """Intercept an agent action, evaluate all compliance rules, and return an outcome.

    All requests — approved and blocked — are written to the immutable audit log.
    Target latency for rule-only checks is sub-50 ms.

    Args:
        req: The validation request body.
        request: FastAPI request object used to access application state.

    Returns:
        :class:`ValidateResponse` containing the approval decision, any violations,
        and a unique request ID for audit correlation.
    """
    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())

    governance = request.app.state.governance
    results: list[RuleResult] = governance.evaluate(
        req.action_type, req.parameters, req.context, req.agent_id
    )

    failures = [r for r in results if not r.passed]
    approved = len(failures) == 0

    violations = [
        ViolationDetail(
            rule_id=r.rule_id,
            violation_code=r.violation_code or "",
            rationale=r.rationale,
        )
        for r in failures
    ]

    if approved:
        rationale = "All rules passed."
    else:
        codes = ", ".join(v.violation_code for v in violations)
        rationale = f"Blocked by rule violations: {codes}."

    latency_ms = (time.perf_counter() - t0) * 1000

    logger.info(
        "validate request_id=%s agent=%s action=%s approved=%s latency_ms=%.2f",
        request_id, req.agent_id, req.action_type, approved, latency_ms,
    )

    await append_entry(
        agent_id=req.agent_id,
        action_type=req.action_type,
        parameters=req.parameters,
        outcome="approved" if approved else "blocked",
        violations=[v.model_dump() for v in violations],
        latency_ms=latency_ms,
    )

    return ValidateResponse(
        approved=approved,
        violations=violations,
        rationale=rationale,
        latency_ms=round(latency_ms, 3),
        request_id=request_id,
    )
