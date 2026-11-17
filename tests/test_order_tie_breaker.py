"""The primary key breaks the ties of the requested ordering.

Rows sharing the sorted value used to come back in whatever order the database
picked for each query: paging through them with LIMIT/OFFSET could repeat some
rows and skip others.
"""

import asyncio
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy_utils import create_database, database_exists, drop_database

from fastapi_crudrouter import CRUDRouter
from fastapi_crudrouter.filtering import OrderByBuilder

# Few distinct values, NULLs included: most rows tie with others.
STATUSES = ["a", "b", "a", None, "b", "a", None, "a", "b", "a"]


def run_async(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _build_app(db_name: str, router_class: type) -> FastAPI:
    sync_uri = f"sqlite:///./{db_name}"
    if database_exists(sync_uri):
        drop_database(sync_uri)
    create_database(sync_uri)

    engine = create_async_engine(f"sqlite+aiosqlite:///./{db_name}")
    session_factory = async_sessionmaker(autoflush=False, bind=engine)
    Base = declarative_base()

    class ItemModel(Base):  # type: ignore[valid-type, misc]
        __tablename__ = "items"
        id = Column(Integer, primary_key=True)
        status = Column(String, nullable=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def get_session() -> Any:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    class ItemSchema(BaseModel):
        model_config = ConfigDict(from_attributes=True)
        id: int
        status: Optional[str] = None

    class ItemCreateSchema(BaseModel):
        status: Optional[str] = None

    app = FastAPI()
    app.include_router(
        router_class(
            schema=ItemSchema,
            db_model=ItemModel,
            db=get_session,
            create_schema=ItemCreateSchema,
            prefix="items",
        )
    )
    return app


class StatusFirstRouter(CRUDRouter):
    """A subclass replacing the requested ordering, as applications do."""

    def _get_order_by(self, pagination: Any) -> Any:  # noqa: ARG002
        return self.db_model.status


@pytest.fixture
def client() -> Any:
    app = run_async(_build_app("test_order_tie_breaker.db", CRUDRouter))
    with TestClient(app) as test_client:
        for status in STATUSES:
            assert test_client.post("/items", json={"status": status}).is_success
        yield test_client


def _all_pages(client: TestClient, order_by: str, limit: int = 3) -> list:
    rows: list = []
    page = 1
    while True:
        res = client.get(
            "/items", params={"order_by": order_by, "limit": limit, "page": page}
        )
        assert res.status_code == 200
        body = res.json()
        rows.extend(body["data"])
        if page >= body["pagination"]["total_pages"]:
            return rows
        page += 1


def _tied_ids_descending(rows: list) -> bool:
    return all(
        prev["id"] > cur["id"]
        for prev, cur in zip(rows, rows[1:])
        if prev["status"] == cur["status"]
    )


@pytest.mark.parametrize("order_by", ["status", "status__DESC"])
def test_pages_hold_every_row_once(client: TestClient, order_by: str) -> None:
    rows = _all_pages(client, order_by)

    ids = [row["id"] for row in rows]
    assert sorted(ids) == list(range(1, len(STATUSES) + 1))


@pytest.mark.parametrize("order_by", ["status", "status__DESC"])
def test_ties_ordered_by_primary_key_descending(
    client: TestClient, order_by: str
) -> None:
    rows = _all_pages(client, order_by)

    assert _tied_ids_descending(rows)


def test_overridden_ordering_keeps_the_tie_breaker() -> None:
    app = run_async(_build_app("test_order_tie_breaker_override.db", StatusFirstRouter))
    with TestClient(app) as test_client:
        for status in STATUSES:
            assert test_client.post("/items", json={"status": status}).is_success

        rows = test_client.get("/items").json()["data"]

    assert len(rows) == len(STATUSES)
    assert _tied_ids_descending(rows)


def test_tie_breaker_is_primary_key_descending() -> None:
    Base = declarative_base()

    class Thing(Base):  # type: ignore[valid-type, misc]
        __tablename__ = "things"
        thing_id = Column(Integer, primary_key=True)
        name = Column(String)

    clause = OrderByBuilder(Thing, "thing_id").tie_breaker()

    assert str(clause) == "things.thing_id DESC"
