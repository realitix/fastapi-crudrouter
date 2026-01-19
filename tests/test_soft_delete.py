"""Tests for soft delete functionality.

Soft delete marks records as deleted instead of removing them from the database.
"""

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy_utils import create_database, database_exists, drop_database

from fastapi_crudrouter import CRUDRouter


async def create_test_app_base(db_uri: str):
    """Create a base test application with async SQLAlchemy setup"""
    sync_uri = db_uri.replace("+aiosqlite", "").replace("sqlite:///", "sqlite:///")

    if database_exists(sync_uri):
        drop_database(sync_uri)
    create_database(sync_uri)

    app = FastAPI()
    engine = create_async_engine(db_uri)
    AsyncSessionLocal = async_sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    Base = declarative_base()

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

    return app, engine, Base, get_session


def run_async(coro):
    """Run async coroutine synchronously"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class MockUser:
    """Mock user for testing"""

    def __init__(self, user_id: int = 1):
        self.id = user_id


class TestSoftDelete:
    """Tests for soft delete feature"""

    @pytest.fixture
    def soft_delete_app(self):
        """Create app with soft delete enabled"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_soft_delete.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)
                is_deleted = Column(Boolean, default=False)
                deleted_at = Column(DateTime, nullable=True)
                deleted_by_id = Column(Integer, nullable=True)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                id: int
                name: str
                price: float
                quantity: int = 0
                is_deleted: bool = False
                deleted_at: Optional[datetime] = None
                deleted_by_id: Optional[int] = None

                class Config:
                    from_attributes = True

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0

            class ItemUpdateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0

            def get_current_user():
                return MockUser(user_id=42)

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                update_schema=ItemUpdateSchema,
                prefix="items",
                current_user_dependency=get_current_user,
                soft_delete=True,
                soft_delete_field="is_deleted",
                soft_delete_value=True,
                soft_delete_timestamp_field="deleted_at",
                soft_delete_by_field="deleted_by_id",
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_soft_delete_marks_item_deleted(self, soft_delete_app):
        """Test that DELETE marks item as deleted instead of removing"""
        app = soft_delete_app
        with TestClient(app) as client:
            # Create item
            res = client.post("/items", json={"name": "Test Item", "price": 10.0})
            assert res.status_code == 201
            item_id = res.json()["id"]

            # Delete item (soft delete)
            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 204

            # Item should not appear in GET all
            res = client.get("/items")
            assert res.status_code == 200
            data = res.json()["data"]
            assert len(data) == 0

    def test_soft_delete_item_not_found_after_deletion(self, soft_delete_app):
        """Test that soft-deleted item returns 404 on GET one"""
        app = soft_delete_app
        with TestClient(app) as client:
            # Create and delete item
            res = client.post("/items", json={"name": "Test Item", "price": 10.0})
            item_id = res.json()["id"]
            client.delete(f"/items/{item_id}")

            # GET one should return 404
            res = client.get(f"/items/{item_id}")
            assert res.status_code == 404

    def test_soft_delete_include_deleted_shows_all(self, soft_delete_app):
        """Test that include_deleted=true shows soft-deleted items"""
        app = soft_delete_app
        with TestClient(app) as client:
            # Create two items
            client.post("/items", json={"name": "Item 1", "price": 10.0})
            res = client.post("/items", json={"name": "Item 2", "price": 20.0})
            item2_id = res.json()["id"]

            # Delete second item
            client.delete(f"/items/{item2_id}")

            # Without include_deleted, only 1 item
            res = client.get("/items")
            assert len(res.json()["data"]) == 1

            # With include_deleted=true, both items
            res = client.get("/items", params={"include_deleted": True})
            assert len(res.json()["data"]) == 2

    def test_soft_delete_cannot_delete_already_deleted(self, soft_delete_app):
        """Test that already soft-deleted items return 404 on delete"""
        app = soft_delete_app
        with TestClient(app) as client:
            # Create and delete item
            res = client.post("/items", json={"name": "Test Item", "price": 10.0})
            item_id = res.json()["id"]
            client.delete(f"/items/{item_id}")

            # Try to delete again - should return 404
            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 404


class TestSoftDeleteNullableField:
    """Test soft delete with nullable fields"""

    def test_soft_delete_with_nullable_field(self):
        """Test soft delete with a nullable field.

        For non-boolean soft delete fields, the implementation filters
        items where the field is NULL (meaning "not deleted").
        """

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_soft_delete_nullable.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                deleted_reason = Column(String, nullable=True, default=None)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                id: int
                name: str
                price: float
                deleted_reason: Optional[str] = None

                class Config:
                    from_attributes = True

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                soft_delete=True,
                soft_delete_field="deleted_reason",
                soft_delete_value="User requested deletion",
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            # Create item (deleted_reason will be NULL)
            res = client.post("/items", json={"name": "Test", "price": 10.0})
            assert res.status_code == 201
            item_id = res.json()["id"]
            assert res.json()["deleted_reason"] is None

            # Item should appear in GET
            res = client.get("/items")
            assert len(res.json()["data"]) == 1

            # Perform soft delete
            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 204

            # Item should not appear in GET anymore
            res = client.get("/items")
            assert len(res.json()["data"]) == 0
