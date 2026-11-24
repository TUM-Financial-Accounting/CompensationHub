import pytest

# backend/.env may point at the production database and turn sign-in on; tests start without
# both, and a test that needs them sets them itself.
SETTINGS = ("DATABASE_URL", "SECRET_KEY", "ADMIN_EMAILS", "LOGIN_REQUIRED", "READ_ONLY",
            "RAILWAY_PUBLIC_DOMAIN")


@pytest.fixture(autouse=True)
def local_settings(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
