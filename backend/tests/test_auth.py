"""Sign-in: the gate on every API route, admin-only writes, passwords and sessions. Registering
and password links write to TEST_DATABASE_URL, a throwaway Postgres (see test_feedback.py)."""

import os
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

OLD = auth.hashed("old password")


@pytest.fixture
def people(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "key")
    monkeypatch.setenv("ADMIN_EMAILS", "Boss@Example.org")
    accounts = {"boss@example.org": ("Boss", auth.hashed("boss password")),
                "ann@example.org": ("Ann", OLD), "new@example.org": ("New", "")}
    monkeypatch.setattr(auth, "accounts", lambda: accounts)
    return accounts


def client(email=None, use="session", stored=None):
    c = TestClient(app, follow_redirects=False)  # no lifespan: the panel is not built
    if email:
        c.cookies.set(auth.SESSION, auth.token(use, email, auth.accounts()[email][1] if stored is None else stored, 1))
    return c


def test_off_without_secret_key_everyone_is_the_local_admin():
    me = client().get("/api/auth/me").json()
    assert me["login"] is False and me["user"]["admin"] is True


def test_refuses_to_start_half_configured(monkeypatch):
    monkeypatch.setenv("LOGIN_REQUIRED", "1")
    with pytest.raises(RuntimeError, match="SECRET_KEY, DATABASE_URL"):
        auth.start()


def test_every_api_route_needs_a_signed_in_user(people):
    assert client().get("/api/summary").status_code == 401
    assert client().get("/api/health").status_code == 200
    assert client().get("/api/auth/me").json()["user"] is None
    assert client("ann@example.org").get("/api/tables").status_code == 200
    forged = client()
    forged.cookies.set(auth.SESSION, auth.token("session", "ann@example.org", OLD, 1)[:-1] + "0")
    assert forged.get("/api/tables").status_code == 401
    assert client("ann@example.org", stored=OLD).get("/api/tables").status_code == 200
    assert client("new@example.org", use="link").get("/api/tables").status_code == 401  # a link is no session
    people["ann@example.org"] = ("Ann", auth.hashed("new password"))  # new password: old sessions end
    assert client("ann@example.org", stored=OLD).get("/api/tables").status_code == 401
    del people["ann@example.org"]  # removed account
    assert client("ann@example.org", stored=OLD).get("/api/tables").status_code == 401


def test_only_admins_change_data(people):
    ann = client("ann@example.org")
    assert ann.delete("/api/tables/execs/rows/999999").status_code == 403
    assert ann.post("/api/feedback/1/done", json={"done": True}).status_code == 403
    assert ann.get("/api/auth/accounts").status_code == 403
    assert ann.post("/api/auth/accounts/ann@example.org/link").status_code == 403
    boss = client("boss@example.org")  # ADMIN_EMAILS ignores case
    assert boss.get("/api/auth/me").json()["user"]["admin"] is True
    assert boss.delete("/api/tables/execs/rows/999999").status_code == 422  # past the gate


def test_sign_in_with_password(people):
    c = client()
    wrong = c.post("/api/auth/signin", json={"email": "ann@example.org", "password": "guess"})
    assert wrong.status_code == 400 and auth.SESSION not in wrong.cookies
    assert c.post("/api/auth/signin", json={"email": "new@example.org", "password": ""}).status_code == 400
    assert c.post("/api/auth/signin", json={"email": " Ann@Example.org ", "password": "old password"}).status_code == 204
    assert c.get("/api/auth/me").json()["user"] == {"email": "ann@example.org", "name": "Ann", "admin": False}
    c.post("/api/auth/logout")
    c.cookies.clear()
    assert c.get("/api/auth/me").json()["user"] is None


def test_sign_in_pauses_after_too_many_wrong_passwords(people):
    c = client()
    for _ in range(auth.MAX_FAILS):
        c.post("/api/auth/signin", json={"email": "boss@example.org", "password": "guess"})
    r = c.post("/api/auth/signin", json={"email": "boss@example.org", "password": "boss password"})
    assert r.status_code == 429
    auth.FAILS.clear()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a throwaway Postgres")
def test_register_and_password_links(monkeypatch, capsys):
    for k, v in {"DATABASE_URL": os.environ["TEST_DATABASE_URL"], "SECRET_KEY": "key",
                 "ADMIN_EMAILS": "boss@example.org"}.items():
        monkeypatch.setenv(k, v)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as db:
        db.execute("DROP TABLE IF EXISTS account")
    try:
        auth.start()  # the admin's account, and their link in the log
        first = capsys.readouterr().out.split("http://localhost:5173/?invite=")[1].strip()
        new = {"email": "boss@example.org", "name": "Not the boss", "password": "taken over"}
        assert client().post("/api/auth/register", json=new).status_code == 409  # nobody registers an admin's address
        boss = client()
        assert boss.post("/api/auth/password", json={"link": first, "password": "boss password"}).status_code == 204
        assert client().post("/api/auth/password", json={"link": first, "password": "used again"}).status_code == 400

        ada = client()
        assert ada.post("/api/auth/register", json={"email": "Ada@Example.org", "name": "Ada", "password": "short"}).status_code == 422
        assert ada.post("/api/auth/register", json={"email": "Ada@Example.org", "name": "Ada", "password": "ada password"}).status_code == 204
        assert ada.get("/api/auth/me").json()["user"] == {"email": "ada@example.org", "name": "Ada", "admin": False}
        assert client().post("/api/auth/register", json={"email": "ada@example.org", "name": "Eve", "password": "eve password"}).status_code == 409

        listed = {a["email"]: a for a in boss.get("/api/auth/accounts").json()}
        assert listed["ada@example.org"]["active"] and listed["boss@example.org"]["admin"]

        reset = boss.post("/api/auth/accounts/ada@example.org/link").json()["link"].split("=")[1]
        assert ada.get("/api/tables").status_code == 200  # the old password works until the link is used
        assert client().post("/api/auth/password", json={"link": reset, "password": "forgot it"}).status_code == 204
        assert ada.get("/api/tables").status_code == 401  # the old session ends with the old password
        assert boss.post("/api/auth/accounts/nobody@example.org/link").status_code == 404

        assert boss.delete("/api/auth/accounts/boss@example.org").status_code == 422
        assert boss.delete("/api/auth/accounts/ada@example.org").status_code == 204
        assert client().post("/api/auth/signin", json={"email": "ada@example.org", "password": "forgot it"}).status_code == 400
    finally:
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as db:
            db.execute("DROP TABLE IF EXISTS account")
        auth._accounts.cache_clear()
