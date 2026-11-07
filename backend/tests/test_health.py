from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_does_not_need_database():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
