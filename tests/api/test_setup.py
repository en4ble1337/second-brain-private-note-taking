import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
from src.core.security import ingest_auth


@pytest_asyncio.fixture
async def setup_client(monkeypatch):
    monkeypatch.setenv("INGEST_TOKEN", "abcdef1234567890")

    from src.main import app
    app.dependency_overrides[ingest_auth] = lambda: None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


async def test_setup_returns_200(setup_client):
    response = await setup_client.get("/setup")
    assert response.status_code == 200


async def test_setup_contains_masked_token(setup_client):
    response = await setup_client.get("/setup")
    assert response.status_code == 200
    assert "abcdef..." in response.text


async def test_setup_contains_ingest_url(setup_client):
    response = await setup_client.get("/setup")
    assert response.status_code == 200
    assert "/api/ingest" in response.text


async def test_setup_uses_lan_ip(setup_client):
    with patch("src.web.router.get_lan_ip", return_value="192.168.1.100"):
        response = await setup_client.get("/setup")
    assert response.status_code == 200
    assert "192.168.1.100" in response.text


async def test_setup_does_not_expose_full_token(setup_client):
    response = await setup_client.get("/setup")
    assert response.status_code == 200
    assert "abcdef1234567890" not in response.text
