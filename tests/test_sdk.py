"""Tests for the AuditorClient SDK (src/sdk/).

All HTTP calls are intercepted with pytest-httpx so no live server is required.
"""
from __future__ import annotations

import pytest
import httpx
from pytest_httpx import HTTPXMock

from src.sdk.client import AuditorClient
from src.sdk.models import ValidationResult, ViolationDetail

BASE_URL = "http://veridact-test"

APPROVED_RESPONSE = {
    "approved": True,
    "violations": [],
    "rationale": "All rules passed.",
    "latency_ms": 3.14,
    "request_id": "aaaa-bbbb-cccc-dddd",
}

BLOCKED_RESPONSE = {
    "approved": False,
    "violations": [
        {
            "rule_id": "finra_ofac_sanctions",
            "violation_code": "OFAC_SANCTIONS_MATCH",
            "rationale": "Field 'recipient_id' value 'SDN-001' is on the OFAC sanctions list.",
        }
    ],
    "rationale": "Blocked by rule violations: OFAC_SANCTIONS_MATCH.",
    "latency_ms": 4.20,
    "request_id": "1111-2222-3333-4444",
}


# ---------------------------------------------------------------------------
# Sync validate()
# ---------------------------------------------------------------------------


def test_validate_returns_validation_result(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL)
    result = client.validate("wire_transfer", {"amount": 100}, {}, "agent-1")
    assert isinstance(result, ValidationResult)


def test_validate_approved(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL)
    result = client.validate("wire_transfer", {"amount": 100}, {}, "agent-1")
    assert result.approved is True
    assert result.violations == []
    assert result.request_id == "aaaa-bbbb-cccc-dddd"
    assert result.latency_ms == pytest.approx(3.14)


def test_validate_blocked(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=BLOCKED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL)
    result = client.validate("wire_transfer", {"amount": 100, "recipient_id": "SDN-001"}, {}, "agent-1")
    assert result.approved is False
    assert len(result.violations) == 1
    v = result.violations[0]
    assert isinstance(v, ViolationDetail)
    assert v.violation_code == "OFAC_SANCTIONS_MATCH"
    assert v.rule_id == "finra_ofac_sanctions"


def test_validate_sends_correct_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL)
    client.validate("payment", {"amount": 500}, {"region": "US"}, "agent-xyz")

    request = httpx_mock.get_requests()[0]
    import json
    body = json.loads(request.content)
    assert body["action_type"] == "payment"
    assert body["parameters"] == {"amount": 500}
    assert body["context"] == {"region": "US"}
    assert body["agent_id"] == "agent-xyz"


def test_validate_sends_api_key_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL, api_key="secret-key")
    client.validate("wire_transfer", {}, {}, "agent-1")

    request = httpx_mock.get_requests()[0]
    assert request.headers.get("x-api-key") == "secret-key"


def test_validate_no_api_key_omits_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL)
    client.validate("wire_transfer", {}, {}, "agent-1")

    request = httpx_mock.get_requests()[0]
    assert "x-api-key" not in request.headers


def test_validate_raises_on_http_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=500)
    client = AuditorClient(base_url=BASE_URL)
    with pytest.raises(httpx.HTTPStatusError):
        client.validate("wire_transfer", {}, {}, "agent-1")


def test_validate_strips_trailing_slash_from_base_url(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL + "/")
    client.validate("wire_transfer", {}, {}, "agent-1")

    request = httpx_mock.get_requests()[0]
    assert str(request.url) == f"{BASE_URL}/validate"


# ---------------------------------------------------------------------------
# Async validate_async()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_async_approved(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL)
    result = await client.validate_async("wire_transfer", {"amount": 100}, {}, "agent-1")
    assert result.approved is True


@pytest.mark.asyncio
async def test_validate_async_blocked(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=BLOCKED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL)
    result = await client.validate_async("wire_transfer", {"recipient_id": "SDN-001"}, {}, "agent-1")
    assert result.approved is False
    assert result.violations[0].violation_code == "OFAC_SANCTIONS_MATCH"


@pytest.mark.asyncio
async def test_validate_async_raises_on_http_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=403)
    client = AuditorClient(base_url=BASE_URL)
    with pytest.raises(httpx.HTTPStatusError):
        await client.validate_async("wire_transfer", {}, {}, "agent-1")


@pytest.mark.asyncio
async def test_validate_async_sends_api_key_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=APPROVED_RESPONSE)
    client = AuditorClient(base_url=BASE_URL, api_key="async-key")
    await client.validate_async("wire_transfer", {}, {}, "agent-1")

    request = httpx_mock.get_requests()[0]
    assert request.headers.get("x-api-key") == "async-key"


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def test_validation_result_model() -> None:
    data = {**APPROVED_RESPONSE}
    result = ValidationResult.model_validate(data)
    assert result.approved is True
    assert result.rationale == "All rules passed."


def test_violation_detail_model() -> None:
    v = ViolationDetail(rule_id="r1", violation_code="CODE", rationale="reason")
    assert v.rule_id == "r1"
    assert v.violation_code == "CODE"
