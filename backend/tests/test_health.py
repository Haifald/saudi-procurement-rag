import os

from fastapi.testclient import TestClient

from app.api import app
import app.retriever as retriever

def test_health():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_without_runtime_dependencies(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(retriever, "EMBEDDINGS_DIR", "missing-embeddings")

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}