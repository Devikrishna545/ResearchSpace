from fastapi.testclient import TestClient

def test_create_app_requires_authentication():
    from app.main import create_app
    client = TestClient(create_app())
    assert client.get("/v1/spaces").status_code == 401
