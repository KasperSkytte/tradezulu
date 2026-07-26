"""Test fixtures.

Environment variables are set before any application module is imported,
because the settings object and the SQLAlchemy engine are both built at import
time.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="tradezulu-tests-"))
os.environ.setdefault("TZ_DATA_DIR", str(_TMP))
os.environ.setdefault("TZ_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("TZ_SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("TZ_ADMIN_USER", "tester")
os.environ.setdefault("TZ_ADMIN_PASSWORD", "correct-horse-battery")
os.environ.setdefault("TZ_INGEST_TOKEN", "test-ingest-token")
os.environ.setdefault("TZ_BCRYPT_ROUNDS", "4")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_client(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "tester", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200, response.text
    return client
