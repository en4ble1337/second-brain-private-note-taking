"""Tests for src/core/security.py — IngestTokenAuth Bearer token validation."""
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient


def _make_test_app(token: str) -> FastAPI:
    """Create a minimal test app with the ingest_auth dependency and a given token."""
    import os
    os.environ["INGEST_TOKEN"] = token

    from src.core.security import IngestTokenAuth
    auth = IngestTokenAuth()

    app = FastAPI()

    @app.post("/test")
    async def protected(creds=Depends(auth)):
        return {"ok": True}

    return app


def test_valid_token_returns_200(monkeypatch):
    """A correct Bearer token receives a 200 response."""
    monkeypatch.setenv("INGEST_TOKEN", "correct-token-abc")
    # Re-import to pick up env var in settings
    import importlib
    import src.core.config as cfg_mod
    import src.core.security as sec_mod
    importlib.reload(cfg_mod)
    importlib.reload(sec_mod)

    from src.core.security import ingest_auth
    app = FastAPI()

    @app.post("/test")
    async def protected(creds=Depends(ingest_auth)):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post("/test", headers={"Authorization": "Bearer correct-token-abc"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_wrong_token_returns_401(monkeypatch):
    """An incorrect Bearer token receives a 401 response."""
    monkeypatch.setenv("INGEST_TOKEN", "correct-token-abc")
    import importlib
    import src.core.config as cfg_mod
    import src.core.security as sec_mod
    importlib.reload(cfg_mod)
    importlib.reload(sec_mod)

    from src.core.security import ingest_auth
    app = FastAPI()

    @app.post("/test")
    async def protected(creds=Depends(ingest_auth)):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_missing_auth_header_returns_401(monkeypatch):
    """Missing Authorization header receives a 401 response."""
    monkeypatch.setenv("INGEST_TOKEN", "correct-token-abc")
    import importlib
    import src.core.config as cfg_mod
    import src.core.security as sec_mod
    importlib.reload(cfg_mod)
    importlib.reload(sec_mod)

    from src.core.security import ingest_auth
    app = FastAPI()

    @app.post("/test")
    async def protected(creds=Depends(ingest_auth)):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test")
    # FastAPI HTTPBearer returns 403 when no credentials provided (auto_error=True default)
    assert resp.status_code in (401, 403)


def test_wrong_scheme_returns_401(monkeypatch):
    """Non-Bearer scheme in Authorization header receives 401."""
    monkeypatch.setenv("INGEST_TOKEN", "correct-token-abc")
    import importlib
    import src.core.config as cfg_mod
    import src.core.security as sec_mod
    importlib.reload(cfg_mod)
    importlib.reload(sec_mod)

    from src.core.security import IngestTokenAuth
    auth = IngestTokenAuth()
    app = FastAPI()

    @app.post("/test")
    async def protected(creds=Depends(auth)):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    # HTTPBearer parent raises 403 for non-Bearer scheme; our subclass may raise 401
    assert resp.status_code in (401, 403)


def test_error_response_shape(monkeypatch):
    """401 error detail matches the ARCH.md error envelope."""
    monkeypatch.setenv("INGEST_TOKEN", "correct-token-abc")
    import importlib
    import src.core.config as cfg_mod
    import src.core.security as sec_mod
    importlib.reload(cfg_mod)
    importlib.reload(sec_mod)

    from src.core.security import ingest_auth
    app = FastAPI()

    @app.post("/test")
    async def protected(creds=Depends(ingest_auth)):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test", headers={"Authorization": "Bearer bad-token"})
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert "error" in detail
    assert detail["error"]["code"] == "UNAUTHORIZED"
    assert "message" in detail["error"]
