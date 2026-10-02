from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_endpoint_requires_token():
    response = client.get("/api/me")
    assert response.status_code == 401


def test_dev_login_and_me():
    login = client.post("/dev/login/archer")
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["subject"] == "dev-archer-001"
    assert me.json()["roles"] == ["archer"]
