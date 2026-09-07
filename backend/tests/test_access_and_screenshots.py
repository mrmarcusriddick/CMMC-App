import hashlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import auth, main, screenshot_validation
from app.database import Base, get_session


@pytest.fixture
def client(monkeypatch):
    settings = SimpleNamespace(app_username="reviewer", app_password="test-only-password-long-enough", session_cookie_secure=False)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def session():
        with Session(engine) as db:
            yield db
    main.app.dependency_overrides[get_session] = session
    # No startup context: these tests use only the isolated in-memory database.
    browser = TestClient(main.app)
    yield browser
    browser.close()
    main.app.dependency_overrides.clear()
    engine.dispose()


def sign_in(client):
    return client.post("/api/session", json={"username": "reviewer", "password": "test-only-password-long-enough"})


@pytest.mark.parametrize("path", ["/api/screenshots", "/api/screenshots/missing/content", "/api/evidence", "/api/accounts", "/api/assessments/missing/evidence.json", "/api/assessments/missing/ssp.md"])
def test_anonymous_reads_are_denied(client, path):
    assert client.get(path).status_code == 401


def test_session_login_logout_tampering_and_expiry(client, monkeypatch):
    assert client.post("/api/session", json={"username": "reviewer", "password": "wrong"}).status_code == 401
    response = sign_in(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
    assert client.get("/api/session").status_code == 200
    assert client.delete("/api/session").status_code == 200
    assert client.get("/api/session").status_code == 401
    sign_in(client)
    token = client.cookies.get(auth.COOKIE_NAME)
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, token + "tampered", path="/api")
    assert client.get("/api/screenshots").status_code == 401
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, token, path="/api")
    monkeypatch.setattr(auth.time, "time", lambda: int(token.split('.')[0]) + 1)
    assert client.get("/api/screenshots").status_code == 401


def test_unconfigured_login_fails_closed(client, monkeypatch):
    monkeypatch.setattr(auth, "configured", lambda: False)
    assert sign_in(client).status_code == 503
    assert client.get("/api/screenshots").status_code == 401


def test_cross_origin_login_and_writes_are_denied(client):
    assert client.post("/api/session", headers={"Origin": "https://untrusted.example"}, json={"username": "reviewer", "password": "test-only-password-long-enough"}).status_code == 403
    sign_in(client)
    assert client.delete("/api/session", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.get("/api/session").status_code == 200


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_screenshot_upload_gallery_download_preserves_bytes_and_hash(client, format, mime):
    image = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(image, format=format)
    data = image.getvalue()
    assert client.post("/api/screenshots?title=Test", content=data, headers={"Content-Type": mime}).status_code == 401
    sign_in(client)
    response = client.post("/api/screenshots?title=Test%20evidence&captured_by=impersonated&contains_cui=true", content=data, headers={"Content-Type": mime})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["sha256"] == hashlib.sha256(data).hexdigest()
    assert item["capturedBy"] == "reviewer"
    assert item["containsCui"] is True
    assert client.get("/api/screenshots").json()["items"][0]["id"] == item["id"]
    result = client.get(f'/api/screenshots/{item["id"]}/content')
    assert result.content == data
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["content-type"] == mime
    client.delete("/api/session")
    assert client.get(f'/api/screenshots/{item["id"]}/content').status_code == 401


def test_invalid_and_oversized_uploads_do_not_create_records(client, monkeypatch):
    sign_in(client)
    headers = {"Content-Type": "image/png"}
    assert client.post("/api/screenshots?title=Test", content=b"not a png", headers=headers).status_code == 422
    image = BytesIO()
    Image.new("RGB", (8, 8)).save(image, format="JPEG")
    assert client.post("/api/screenshots?title=Test", content=image.getvalue(), headers=headers).status_code == 415
    monkeypatch.setattr(screenshot_validation, "MAX_BYTES", 4)
    assert client.post("/api/screenshots?title=Test", content=b"12345", headers=headers).status_code == 413
    assert client.get("/api/screenshots").json()["items"] == []
