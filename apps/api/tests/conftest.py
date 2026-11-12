import os
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Tests may use the local PostgreSQL URL, never operator sessions or provider keys.
os.environ.update(APP_ENV="test", APP_ACCESS_KEY="", PUBLIC_BASE_URL="http://testserver", COOKIE_SECURE="false",
                  PAYPAL_CLIENT_ID="", PAYPAL_CLIENT_SECRET="", PAYPAL_MERCHANT_ID="", PAYPAL_WEBHOOK_ID="", GROQ_API_KEY="")
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


@pytest.fixture()
def database():
    from mandate import models
    from mandate.db import Base
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL PostgreSQL is required for integration tests")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    admin = create_engine(url)
    schema = "test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture()
def client(database, monkeypatch):
    from mandate.db import get_db
    from mandate.main import app

    def isolated_db():
        with database() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db] = isolated_db
    app.state.testing = True
    monkeypatch.setattr("mandate.http_boundary.SessionLocal", database)
    monkeypatch.setattr("mandate.agents.router.SessionLocal", database)
    monkeypatch.setattr("mandate.reconciliation.SessionLocal", database)
    with TestClient(app) as client:
        session = client.get("/api/session").json()
        client.headers["X-CSRF-Token"] = session["csrf_token"]
        yield client
    app.dependency_overrides.clear()
    app.state.testing = False
