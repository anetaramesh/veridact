from __future__ import annotations
import os
import tempfile
from pathlib import Path
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Stub data that mirrors the old YAML stubs — used by the mock data provider
# ---------------------------------------------------------------------------
_STUB_SDN_IDS = frozenset(["SDN-001", "SDN-002", "SDN-003", "BLOCKED-ENTITY-A", "BLOCKED-ENTITY-B"])
_STUB_FROZEN_ACCOUNTS = frozenset(["FROZEN-ACC-001", "FROZEN-ACC-002", "FROZEN-ACC-003"])
_STUB_WIRE_THRESHOLD = 1_000_000.0


class _StubDataProvider:
    """Test double for LiveDataProvider using the old YAML stub values."""

    def is_sanctioned(self, entity_id: str) -> bool:
        return entity_id in _STUB_SDN_IDS

    def is_account_restricted(self, account_id: str) -> bool:
        return account_id in _STUB_FROZEN_ACCOUNTS

    def get_wire_threshold(self) -> float:
        return _STUB_WIRE_THRESHOLD


@pytest.fixture(scope="session")
def tmp_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "test_audit.db"
    os.environ["AUDIT_DB_PATH"] = str(db)
    return db


@pytest.fixture(scope="session")
def app(tmp_db):
    import src.api.main as _main_mod
    from src.api.main import create_app

    # Patch module-level names so the lifespan picks up the stub provider.
    # The patch must stay in place until after TestClient enters context (lifespan runs),
    # so we restore only after the session client is torn down.
    _orig_client = _main_mod.FinraApiClient
    _orig_provider = _main_mod.FinraDataProvider

    _main_mod.FinraApiClient = lambda: None  # type: ignore[assignment]
    _main_mod.FinraDataProvider = lambda _client, **_kw: _StubDataProvider()  # type: ignore[assignment]
    os.environ.setdefault("FINRA_CLIENT_ID", "test-id")
    os.environ.setdefault("FINRA_CLIENT_SECRET", "test-secret")

    application = create_app()

    yield application

    # Restore after session ends (after all clients have torn down)
    _main_mod.FinraApiClient = _orig_client  # type: ignore[assignment]
    _main_mod.FinraDataProvider = _orig_provider  # type: ignore[assignment]


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as c:
        yield c




@pytest_asyncio.fixture
async def async_client(client, app):
    """Async client sharing the session app (lifespan already started by client)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
