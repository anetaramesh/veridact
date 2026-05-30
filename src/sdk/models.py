from __future__ import annotations

from pydantic import BaseModel


class ViolationDetail(BaseModel):
    """A single compliance rule violation returned by the Veridact API.

    Attributes:
        rule_id: ID of the rule that was violated.
        violation_code: Short machine-readable code (e.g. ``OFAC_SANCTIONS_MATCH``).
        rationale: Human-readable explanation of why the rule failed.
    """

    rule_id: str
    violation_code: str
    rationale: str


class ValidationResult(BaseModel):
    """Complete outcome of a Veridact validation call.

    Attributes:
        approved: ``True`` if the action is permitted; ``False`` if blocked.
        violations: List of violations (empty when ``approved`` is ``True``).
        rationale: Summary rationale string.
        latency_ms: Server-side rule evaluation latency in milliseconds.
        request_id: UUID that correlates this result to the server audit log.
    """

    approved: bool
    violations: list[ViolationDetail]
    rationale: str
    latency_ms: float
    request_id: str
