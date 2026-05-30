"""Latency regression test: p99 rule-only evaluation must be under 10 ms."""
from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest
import yaml

from src.engine.agt_adapter import AGTAdapter
from src.engine.models import PolicyRule, Severity
from src.rules.models import CheckType

_N_REQUESTS = 100
_P99_LIMIT_MS = 10.0


@pytest.fixture(scope="module")
def fast_adapter(tmp_path_factory: pytest.TempPathFactory) -> AGTAdapter:
    """AGTAdapter with a minimal in-memory rule set for latency measurement."""
    rules_dir = tmp_path_factory.mktemp("latency_rules")

    rule = PolicyRule(
        id="finra_ofac_sanctions",
        name="OFAC Sanctions Check",
        regulation_ref="FINRA Rule 3310; BSA 31 U.S.C. § 5318(l)",
        description="Blocks wire transfers to sanctioned recipients.",
        check_type=CheckType.sanctions_list,
        action_types=["wire_transfer"],
        params={"field": "recipient_id", "sanctions_list": ["SDN-001"]},
        violation_code="OFAC_SANCTIONS_MATCH",
        severity=Severity.hard_block,
        rationale_template="Recipient '{recipient_id}' is on the OFAC SDN list.",
    )
    (rules_dir / "finra_ofac_sanctions.yaml").write_text(yaml.dump(rule.model_dump(mode="json")))

    return AGTAdapter(rules_dir=rules_dir)


def test_p99_latency_under_10ms(fast_adapter: AGTAdapter) -> None:
    """Fire 100 rule-only evaluations and assert p99 wall-clock time < 10 ms."""
    latencies: list[float] = []

    for i in range(_N_REQUESTS):
        start = time.perf_counter()
        result = fast_adapter.evaluate(
            action_type="wire_transfer",
            parameters={"recipient_id": f"CLEAN-{i}", "amount": 5000},
            context={},
            agent_id=f"latency-agent-{i}",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)
        assert result is not None  # sanity

    latencies.sort()
    p99_index = int(0.99 * _N_REQUESTS) - 1
    p99_ms = latencies[max(p99_index, 0)]
    p50_ms = statistics.median(latencies)

    print(f"\nLatency over {_N_REQUESTS} requests — p50={p50_ms:.3f}ms  p99={p99_ms:.3f}ms")

    assert p99_ms < _P99_LIMIT_MS, (
        f"p99 latency {p99_ms:.3f}ms exceeds {_P99_LIMIT_MS}ms limit. "
        f"p50={p50_ms:.3f}ms"
    )
