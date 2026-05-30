from __future__ import annotations
import os
import tempfile
from pathlib import Path
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="session")
def tmp_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "test_audit.db"
    # Set env var so the app lifespan picks up this path
    os.environ["AUDIT_DB_PATH"] = str(db)
    return db


@pytest.fixture(scope="session")
def app(tmp_db):
    from src.api.main import create_app
    return create_app()


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def async_client(client, app):
    """Async client sharing the session app (lifespan already started by client)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
