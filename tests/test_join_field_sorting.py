"""Tests for sorting by join fields.

Verifies that join_fields (single relationship fields) are included
in the computed columns set, enabling ORDER BY on joined columns.
"""

import asyncio
from typing import Annotated, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
import pytest
from sqlalchemy import Column, ForeignKey, Integer, String, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy_utils import create_database, database_exists, drop_database

from fastapi_crudrouter import CRUDRouter


def _create_db(db_uri: str):
    """Create (or recreate) a test database."""
    sync_uri = db_uri.replace("+aiosqlite", "").replace(
        "sqlite:///", "sqlite:///"
    )
    if database_exists(sync_uri):
        drop_database(sync_uri)
    create_database(sync_uri)


def run_async(coro):
    """Run async coroutine synchronously"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestJoinFieldSortingUnit:
    """Unit tests: join_fields are registered as computed columns."""

    def test_join_fields_in_computed_columns(self):
        """Verify that join_fields keys are added to
        OrderByBuilder's computed columns."""

        async def _setup():
            db_uri = "sqlite+aiosqlite:///./test_join_sort_unit.db"
            _create_db(db_uri)

            engine = create_async_engine(db_uri)
            AsyncSessionLocal = async_sessionmaker(
                autocommit=False, autoflush=False, bind=engine
            )
            Base = declarative_base()

            class CategoryModel(Base):
                __tablename__ = "categories"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                title = Column(String)
                category_id = Column(
                    Integer, ForeignKey("categories.id"), nullable=True
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async def get_session():
                async with AsyncSessionLocal() as session:
                    try:
                        yield session
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise
                    finally:
                        await session.close()

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None

            class ItemGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None
                category_name: Annotated[
                    Optional[str], CategoryModel.name
                ] = None

            class ItemCreateSchema(BaseModel):
                title: str
                category_id: Optional[int] = None

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                get_all_schema=ItemGetAllSchema,
                prefix="items",
            )

            return router

        router = run_async(_setup())
        computed = router._order_builder._computed_columns
        assert "category_name" in computed

    def test_join_fields_and_custom_func_fields_both_in_computed(self):
        """Verify both join_fields and custom_func_fields are included."""

        async def _setup():
            db_uri = "sqlite+aiosqlite:///./test_join_sort_both.db"
            _create_db(db_uri)

            engine = create_async_engine(db_uri)
            AsyncSessionLocal = async_sessionmaker(
                autocommit=False, autoflush=False, bind=engine
            )
            Base = declarative_base()

            class CategoryModel(Base):
                __tablename__ = "categories"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                title = Column(String)
                category_id = Column(
                    Integer, ForeignKey("categories.id"), nullable=True
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            def add_item_count(query):
                return query.add_columns(
                    func.count().over().label("item_count")
                )

            async def get_session():
                async with AsyncSessionLocal() as session:
                    try:
                        yield session
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise
                    finally:
                        await session.close()

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None

            class ItemGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None
                category_name: Annotated[
                    Optional[str], CategoryModel.name
                ] = None
                item_count: Annotated[int, add_item_count]

            class ItemCreateSchema(BaseModel):
                title: str
                category_id: Optional[int] = None

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                get_all_schema=ItemGetAllSchema,
                prefix="items",
            )

            return router

        router = run_async(_setup())
        computed = router._order_builder._computed_columns
        assert "category_name" in computed
        assert "item_count" in computed


class TestJoinFieldSortingIntegration:
    """Integration tests: sorting by join field via HTTP."""

    @pytest.fixture
    def join_sort_app(self):
        """Create app with a join field in get_all_schema."""

        async def _setup():
            db_uri = "sqlite+aiosqlite:///./test_join_sort_integration.db"
            _create_db(db_uri)

            engine = create_async_engine(db_uri)
            AsyncSessionLocal = async_sessionmaker(
                autocommit=False, autoflush=False, bind=engine
            )
            Base = declarative_base()

            class CategoryModel(Base):
                __tablename__ = "categories"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                title = Column(String)
                category_id = Column(
                    Integer, ForeignKey("categories.id"), nullable=True
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # Seed categories
            async with AsyncSessionLocal() as session:
                session.add_all([
                    CategoryModel(id=1, name="Alpha"),
                    CategoryModel(id=2, name="Charlie"),
                    CategoryModel(id=3, name="Bravo"),
                ])
                await session.commit()

            async def get_session():
                async with AsyncSessionLocal() as session:
                    try:
                        yield session
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise
                    finally:
                        await session.close()

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None

            class ItemGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None
                category_name: Annotated[
                    Optional[str], CategoryModel.name
                ] = None

            class ItemCreateSchema(BaseModel):
                title: str
                category_id: Optional[int] = None

            app = FastAPI()
            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                get_all_schema=ItemGetAllSchema,
                prefix="items",
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_sort_by_join_field_asc(self, join_sort_app):
        """Test sorting by a join field in ascending order."""
        with TestClient(join_sort_app) as client:
            client.post("/items", json={"title": "Item C", "category_id": 2})
            client.post("/items", json={"title": "Item A", "category_id": 1})
            client.post("/items", json={"title": "Item B", "category_id": 3})

            res = client.get(
                "/items", params={"order_by": "category_name"}
            )
            assert res.status_code == 200
            data = res.json()["data"]

            assert len(data) == 3
            # Alpha, Bravo, Charlie
            assert data[0]["category_name"] == "Alpha"
            assert data[1]["category_name"] == "Bravo"
            assert data[2]["category_name"] == "Charlie"

    def test_sort_by_join_field_desc(self, join_sort_app):
        """Test sorting by a join field in descending order."""
        with TestClient(join_sort_app) as client:
            client.post("/items", json={"title": "Item C", "category_id": 2})
            client.post("/items", json={"title": "Item A", "category_id": 1})
            client.post("/items", json={"title": "Item B", "category_id": 3})

            res = client.get(
                "/items",
                params={"order_by": "category_name__DESC"},
            )
            assert res.status_code == 200
            data = res.json()["data"]

            assert len(data) == 3
            # Charlie, Bravo, Alpha
            assert data[0]["category_name"] == "Charlie"
            assert data[1]["category_name"] == "Bravo"
            assert data[2]["category_name"] == "Alpha"

    def test_default_order_by_join_field(self):
        """Test default_order_by with a join field name."""

        async def _setup():
            db_uri = "sqlite+aiosqlite:///./test_default_join_sort.db"
            _create_db(db_uri)

            engine = create_async_engine(db_uri)
            AsyncSessionLocal = async_sessionmaker(
                autocommit=False, autoflush=False, bind=engine
            )
            Base = declarative_base()

            class CategoryModel(Base):
                __tablename__ = "categories"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                title = Column(String)
                category_id = Column(
                    Integer, ForeignKey("categories.id"), nullable=True
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # Seed categories
            async with AsyncSessionLocal() as session:
                session.add_all([
                    CategoryModel(id=1, name="Zebra"),
                    CategoryModel(id=2, name="Apple"),
                    CategoryModel(id=3, name="Mango"),
                ])
                await session.commit()

            async def get_session():
                async with AsyncSessionLocal() as session:
                    try:
                        yield session
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise
                    finally:
                        await session.close()

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None

            class ItemGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                title: str
                category_id: Optional[int] = None
                category_name: Annotated[
                    Optional[str], CategoryModel.name
                ] = None

            class ItemCreateSchema(BaseModel):
                title: str
                category_id: Optional[int] = None

            app = FastAPI()
            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                get_all_schema=ItemGetAllSchema,
                prefix="items",
                default_order_by="category_name",
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            client.post("/items", json={"title": "Item Z", "category_id": 1})
            client.post("/items", json={"title": "Item A", "category_id": 2})
            client.post("/items", json={"title": "Item M", "category_id": 3})

            res = client.get("/items")
            assert res.status_code == 200
            data = res.json()["data"]

            assert len(data) == 3
            # Default ordering: Apple, Mango, Zebra
            assert data[0]["category_name"] == "Apple"
            assert data[1]["category_name"] == "Mango"
            assert data[2]["category_name"] == "Zebra"
