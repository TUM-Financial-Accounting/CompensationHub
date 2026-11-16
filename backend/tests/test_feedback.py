"""Feedback routes. The round trip writes to TEST_DATABASE_URL, a throwaway Postgres, never to
DATABASE_URL, so a production database in backend/.env stays clean:
`docker run --rm -d -p 5433:5432 -e POSTGRES_PASSWORD=x postgres:17` and
`TEST_DATABASE_URL=postgresql://postgres:x@localhost:5433/postgres uv run pytest tests/test_feedback.py`."""

import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)  # no lifespan: the panel is not built


def test_off_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert client.get("/api/feedback").status_code == 503


def test_rejects_blank_post_and_non_images():
    assert client.post("/api/feedback", json={"body": "   "}).status_code == 422
    svg = {"type": "image/svg+xml", "data": "PHN2Zz4="}
    assert client.post("/api/feedback", json={"body": "x", "photos": [svg]}).status_code == 422


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a throwaway Postgres")
def test_post_round_trips(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    post = client.post("/api/feedback", json={"author": " Ada ", "body": "Line one\nline two"}).json()
    assert post["author"] == "Ada" and post["body"] == "Line one\nline two"
    assert post["reply_to"] is None and post["photos"] == [] and post["done"] is False
    assert client.get("/api/feedback").json()[0] == post

    png = b"\x89PNG\r\n\x1a\n fake"
    reply = client.post("/api/feedback", json={"body": "Thanks", "reply_to": post["id"],
                                               "photos": [{"type": "image/png", "data": base64.b64encode(png).decode()}]}).json()
    assert reply["reply_to"] == post["id"] and len(reply["photos"]) == 1
    photo = client.get(f"/api/feedback/photos/{reply['photos'][0]}")
    assert photo.content == png and photo.headers["content-type"] == "image/png"
    assert photo.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/feedback").json()[0] == reply
    # anyone marks a post as done and open again; replies and unknown posts cannot be marked
    mark = lambda i, done: client.post(f"/api/feedback/{i}/done", json={"done": done})  # noqa: E731
    assert mark(post["id"], True).json() == {**post, "done": True}
    assert mark(post["id"], False).json() == post
    assert mark(reply["id"], True).status_code == 404 and mark(10**9, True).status_code == 404
    # one level of replies only, and only to posts that exist
    assert client.post("/api/feedback", json={"body": "x", "reply_to": reply["id"]}).status_code == 422
    assert client.post("/api/feedback", json={"body": "x", "reply_to": 10**9}).status_code == 422
