"""Feedback routes. The round trip writes to TEST_DATABASE_URL, a throwaway Postgres, never to
DATABASE_URL, so a production database in backend/.env stays clean:
`docker run --rm -d -p 5433:5432 -e POSTGRES_PASSWORD=x postgres:17` and
`TEST_DATABASE_URL=postgresql://postgres:x@localhost:5433/postgres uv run pytest tests/test_feedback.py`."""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)  # no lifespan: the panel is not built


def test_off_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert client.get("/api/feedback").status_code == 503


def test_rejects_blank_post():
    assert client.post("/api/feedback", json={"body": "   "}).status_code == 422


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a throwaway Postgres")
def test_post_round_trips(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    post = client.post("/api/feedback", json={"author": " Ada ", "body": "Line one\nline two"}).json()
    assert post["author"] == "Ada" and post["body"] == "Line one\nline two"
    assert client.get("/api/feedback").json()[0] == post
