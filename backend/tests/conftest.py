import os

import asyncio

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
from app.core.config import settings  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_DATABASE_URL = settings.test_database_url
TEST_DATABASE_SYNC_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def ensure_test_database_exists() -> None:
    admin_url = TEST_DATABASE_SYNC_URL.rsplit("/", 1)[0] + "/postgres"
    db_name = TEST_DATABASE_SYNC_URL.rsplit("/", 1)[1]

    with psycopg.connect(admin_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (db_name,),
        ).fetchone()
        if row is None:
            conn.execute(f'CREATE DATABASE "{db_name}"')


def run_migrations() -> None:
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://"),
    )
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database() -> None:
    ensure_test_database_exists()
    run_migrations()


@pytest.fixture
def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    asyncio.run(engine.dispose())


@pytest.fixture
def db_session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_database() -> None:
    with psycopg.connect(TEST_DATABASE_SYNC_URL) as conn:
        conn.execute("TRUNCATE job_events, workers, jobs RESTART IDENTITY CASCADE")
        conn.commit()
    yield


@pytest.fixture
def client(db_session_factory):
    async def override_get_db():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def job_payload() -> dict:
    return {
        "job_type": "sleep",
        "payload": {"seconds": 3},
        "max_attempts": 3,
        "idempotency_key": "test-job-1",
    }
