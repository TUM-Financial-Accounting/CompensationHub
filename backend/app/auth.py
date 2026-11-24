"""Register and sign in with email and password; no outside service. Anyone can register (the
app sends no email, so an address is not checked). Admins see every account on the Accounts page,
remove accounts, and for a forgotten password make a one-time link that they pass on themselves.

Accounts live in Postgres (DATABASE_URL) with scrypt password hashes; the session is a signed,
http-only cookie for 7 days. Sessions and links carry a stamp of the password hash, so a new
password or a removed account ends them (within ACCOUNTS_TTL seconds, the accounts cache). Who is
an admin comes from ADMIN_EMAILS on every request; their accounts are made at startup, and an admin
without a password finds a link in the server log; their address cannot be registered by anyone
else, as it has an account from the start. Without SECRET_KEY sign-in is off and every
visitor is a local admin, as in development; LOGIN_REQUIRED (set in the Dockerfile) makes the
server refuse to start that way.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from functools import lru_cache

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from . import schemas as s

SESSION = "session"
SESSION_DAYS, LINK_DAYS = 7, 7
ACCOUNTS_TTL = 30  # seconds a removed account or an old password stays signed in, at most
MAX_FAILS, FAIL_MINUTES = 10, 15  # wrong passwords for one account before sign-in pauses
LOCAL = {"email": "", "name": "Local", "admin": True}

router = APIRouter(prefix="/api/auth", include_in_schema=False)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def flag(name: str) -> bool:
    return env(name).lower() not in ("", "0", "false", "no")


def on() -> bool:
    return bool(env("SECRET_KEY"))


def admins() -> set[str]:
    return {e.strip().lower() for e in env("ADMIN_EMAILS").split(",") if e.strip()}


# --------------------------------------------------------------------------- accounts

ACCOUNTS = """CREATE TABLE IF NOT EXISTS account (
    email text PRIMARY KEY,
    name text NOT NULL,
    password text NOT NULL DEFAULT '',
    created timestamptz NOT NULL DEFAULT now())"""


def db() -> psycopg.Connection:
    c = psycopg.connect(env("DATABASE_URL"), connect_timeout=5)
    c.execute(ACCOUNTS)
    return c


@lru_cache(maxsize=1)
def _accounts(tick: int) -> dict[str, tuple[str, str]]:
    with db() as c:
        return {e: (n, p) for e, n, p in c.execute("SELECT email, name, password FROM account")}


def accounts() -> dict[str, tuple[str, str]]:
    """Every account as email: (name, password hash; '' until the link is used), read again every
    ACCOUNTS_TTL seconds and after every change made here."""
    return _accounts(int(time.time() // ACCOUNTS_TTL))


def start() -> None:
    """At startup: a hosted dashboard never runs without sign-in by accident; every admin has an
    account, and one without a password gets a link in the log."""
    missing = [v for v in ("SECRET_KEY", "DATABASE_URL") if not env(v)]
    if missing and (on() or flag("LOGIN_REQUIRED")):
        raise RuntimeError(f"Sign-in needs {', '.join(missing)} (see backend/.env.example).")
    if not on():
        return
    with db() as c:
        for email in sorted(admins()):
            stored = c.execute("""INSERT INTO account (email, name) VALUES (%s, %s)
                ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING password""",
                               (email, email.split("@")[0])).fetchone()[0]
            if not stored:
                domain = env("RAILWAY_PUBLIC_DOMAIN")
                site = f"https://{domain}" if domain else "http://localhost:5173"
                print(f"Choose the password of admin {email}: {site}{link(email, stored)}", flush=True)
    _accounts.cache_clear()


# --------------------------------------------------------------------------- passwords


def scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def hashed(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}:{scrypt(password, salt).hex()}"


def matches(password: str, stored: str) -> bool:
    """Whether the password fits the hash; as slow for no account, so timing tells nothing."""
    salt, _, digest = (stored or f"{'0' * 32}:").partition(":")
    return hmac.compare_digest(scrypt(password, bytes.fromhex(salt)).hex(), digest) and bool(stored)


# --------------------------------------------------------------------------- signed tokens


def mac(body: str) -> str:
    return hmac.new(env("SECRET_KEY").encode(), body.encode(), hashlib.sha256).hexdigest()


def sign(data: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")  # no cookie quoting
    return f"{body}.{mac(body)}"


def unsign(value: str | None, use: str) -> dict | None:
    """The token's data if it carries our signature, is meant for `use` and has not expired."""
    body, _, sig = (value or "").rpartition(".")
    if not body or not hmac.compare_digest(sig.encode(), mac(body).encode()):  # bytes: a cookie may hold anything
        return None
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    return data if data.get("use") == use and data.get("exp", 0) > time.time() else None


def stamp(stored: str) -> str:
    return mac("password:" + stored)[:16]


def token(use: str, email: str, stored: str, days: int) -> str:
    """A session ('session') or a one-time link ('link'); both end when the password changes."""
    return sign({"use": use, "email": email, "v": stamp(stored), "exp": time.time() + days * 86400})


def holder(value: str | None, use: str) -> tuple[str, str, str] | None:
    """(email, name, password hash) of a valid token's account, if it still exists unchanged."""
    t = unsign(value, use)
    name, stored = accounts().get(t["email"], (None, "")) if t else (None, "")
    if name is None or not hmac.compare_digest(t["v"], stamp(stored)):
        return None
    return t["email"], name, stored


def link(email: str, stored: str) -> str:
    return "/?invite=" + token("link", email, stored, LINK_DAYS)


# --------------------------------------------------------------------------- who is signed in


def user(request: Request) -> dict | None:
    """The signed-in user, or None; everyone is the local admin when sign-in is off."""
    if not on():
        return LOCAL
    h = holder(request.cookies.get(SESSION), "session")
    if h is None or not h[2]:
        return None
    return {"email": h[0], "name": h[1], "admin": h[0] in admins()}


def admin(request: Request) -> dict:
    """Dependency of the routes that change data, moderate feedback or manage accounts."""
    u = user(request)
    if u is None:
        raise HTTPException(401, "Sign in first.")
    if not u["admin"]:
        raise HTTPException(403, "Only admins can do this.")
    return u


def signed_in(response: Response, request: Request, email: str, stored: str) -> None:
    response.set_cookie(SESSION, token("session", email, stored, SESSION_DAYS), max_age=SESSION_DAYS * 86400,
                        path="/", httponly=True, samesite="lax", secure=request.url.scheme == "https")


FAILS: dict[str, list[float]] = {}  # ponytail: per process and lost on restart; one worker is enough


@router.post("/signin", status_code=204)
def signin(body: s.SignIn, request: Request, response: Response):
    now = time.time()
    fails = FAILS[body.email] = [t for t in FAILS.get(body.email, []) if t > now - FAIL_MINUTES * 60]
    if len(fails) >= MAX_FAILS:
        raise HTTPException(429, f"Too many wrong passwords: try again in {FAIL_MINUTES} minutes.")
    name, stored = accounts().get(body.email, ("", ""))
    if not matches(body.password, stored):
        if not stored:
            del FAILS[body.email]  # count only for real accounts, so the dict stays small
        else:
            fails.append(now)
        raise HTTPException(400, "Wrong email or password.")  # 401 would reload the page
    del FAILS[body.email]
    signed_in(response, request, body.email, stored)


@router.post("/register", status_code=204)
def register(body: s.Register, request: Request, response: Response):
    """Make an account and sign in; an address with an account already cannot register again."""
    stored = hashed(body.password)
    with db() as c:
        made = c.execute("INSERT INTO account (email, name, password) VALUES (%s, %s, %s) ON CONFLICT (email) DO NOTHING",
                         (body.email, body.name, stored)).rowcount
    _accounts.cache_clear()
    if not made:
        raise HTTPException(409, "This email has an account already: sign in, or ask an admin for a password link.")
    signed_in(response, request, body.email, stored)


@router.post("/password", status_code=204)
def set_password(body: s.NewPassword, request: Request, response: Response):
    """Choose a new password with a link from an admin (or the server log); signs in. Works once."""
    h = holder(body.link, "link")
    stored = hashed(body.password)
    with db() as c:
        done = h and c.execute("UPDATE account SET password = %s WHERE email = %s AND password = %s",
                               (stored, h[0], h[2])).rowcount
    _accounts.cache_clear()
    if not done:
        raise HTTPException(400, "This link has expired or was used already: ask an admin for a new one.")
    signed_in(response, request, h[0], stored)


@router.post("/logout")
def logout():
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie(SESSION, path="/")
    return r


@router.get("/me", response_model=s.Session)
def me(request: Request):
    """Who is signed in (None when signed out) and whether sign-in is on."""
    return {"user": user(request), "login": on()}


@router.get("/accounts", response_model=list[s.Account], dependencies=[Depends(admin)])
def list_accounts():
    with db() as c:
        rows = c.execute("SELECT email, name, password <> '', created FROM account ORDER BY lower(name)").fetchall()
    return [{"email": e, "name": n, "active": a, "admin": e in admins(), "created": t} for e, n, a, t in rows]


@router.post("/accounts/{email}/link", response_model=s.PasswordLink, dependencies=[Depends(admin)])
def password_link(email: str):
    """A one-time link to choose a new password, for a forgotten one; the old password keeps
    working until the link is used."""
    with db() as c:
        row = c.execute("SELECT password FROM account WHERE email = %s", (email.lower(),)).fetchone()
    if row is None:
        raise HTTPException(404, "No such account.")
    return {"link": link(email.lower(), row[0]),
            "expires": datetime.fromtimestamp(time.time() + LINK_DAYS * 86400, timezone.utc)}


@router.delete("/accounts/{email}", status_code=204, dependencies=[Depends(admin)])
def remove(email: str):
    """Remove an account; its sessions end within ACCOUNTS_TTL seconds."""
    if email.lower() in admins():
        raise HTTPException(422, "Admins come from ADMIN_EMAILS: remove the address there.")
    with db() as c:
        c.execute("DELETE FROM account WHERE email = %s", (email.lower(),))
    _accounts.cache_clear()
