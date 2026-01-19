"""Integration tests combining multiple new features."""

import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException
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

    def __init__(self, user_id: int = 1, school_id: int = 100):
        self.id = user_id
        self.school_id = school_id


class TestIntegrationAllFeatures:
    """Integration tests combining multiple new features"""

    @pytest.fixture
    def full_feature_app(self):
        """Create app with all new features enabled"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_full_features.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)
                display_order = Column(Integer, default=0)
                school_id = Column(Integer, nullable=True)
                created_by_id = Column(Integer, nullable=True)
                is_deleted = Column(Boolean, default=False)
                deleted_at = Column(DateTime, nullable=True)
                deleted_by_id = Column(Integer, nullable=True)
                is_locked = Column(Boolean, default=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            hook_tracker = {"after_create": 0, "after_update": 0, "after_delete": 0}

            async def after_create(model, user, db):
                hook_tracker["after_create"] += 1

            async def after_update(model, user, db):
                hook_tracker["after_update"] += 1

            async def after_delete(item_id, user, db):
                hook_tracker["after_delete"] += 1

            async def delete_validator(item_id, user, db):
                item = await db.get(ItemModel, item_id)
                if item and item.is_locked:
                    raise HTTPException(400, "Cannot delete locked item")

            def get_current_user():
                return MockUser(user_id=42, school_id=123)

            def get_defaults(user):
                return {"school_id": user.school_id, "created_by_id": user.id}

            class ItemSchema(BaseModel):
                id: int
                name: str
                price: float
                quantity: int = 0
                display_order: int = 0
                school_id: Optional[int] = None
                created_by_id: Optional[int] = None
                is_deleted: bool = False
                is_locked: bool = False

                class Config:
                    from_attributes = True

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0
                display_order: int = 0
                school_id: Optional[int] = None
                created_by_id: Optional[int] = None
                is_locked: bool = False

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                current_user_dependency=get_current_user,
                create_defaults=get_defaults,
                delete_validator=delete_validator,
                default_order_by="display_order",
                soft_delete=True,
                soft_delete_field="is_deleted",
                soft_delete_timestamp_field="deleted_at",
                soft_delete_by_field="deleted_by_id",
                after_create=after_create,
                after_update=after_update,
                after_delete=after_delete,
                bulk_create_route=True,
                bulk_update_route=True,
                bulk_delete_route=True,
            )
            app.include_router(router)
            return app, hook_tracker

        return run_async(_setup())

    def test_create_with_defaults_and_hook(self, full_feature_app):
        """Test that create_defaults and after_create hook work together"""
        app, hook_tracker = full_feature_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Test", "price": 10.0})
            assert res.status_code == 201

            data = res.json()
            assert data["school_id"] == 123
            assert data["created_by_id"] == 42
            assert hook_tracker["after_create"] == 1

    def test_soft_delete_with_validator_and_hook(self, full_feature_app):
        """Test soft delete with delete_validator and after_delete hook"""
        app, hook_tracker = full_feature_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "To Delete", "price": 10.0})
            item_id = res.json()["id"]

            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 204
            assert hook_tracker["after_delete"] == 1

            res = client.get("/items")
            assert len(res.json()["data"]) == 0

    def test_default_order_by_applied(self, full_feature_app):
        """Test that default_order_by is applied"""
        app, _ = full_feature_app
        with TestClient(app) as client:
            client.post(
                "/items", json={"name": "Third", "price": 30.0, "display_order": 3}
            )
            client.post(
                "/items", json={"name": "First", "price": 10.0, "display_order": 1}
            )
            client.post(
                "/items", json={"name": "Second", "price": 20.0, "display_order": 2}
            )

            res = client.get("/items")
            data = res.json()["data"]

            assert data[0]["display_order"] == 1
            assert data[1]["display_order"] == 2
            assert data[2]["display_order"] == 3

    def test_bulk_operations_with_hooks(self, full_feature_app):
        """Test bulk operations trigger hooks appropriately"""
        app, hook_tracker = full_feature_app
        with TestClient(app) as client:
            items = [
                {"name": f"Bulk Item {i}", "price": float(i * 10)} for i in range(3)
            ]
            res = client.post("/items/bulk", json=items)
            assert res.status_code == 201
            assert hook_tracker["after_create"] >= 3

    def test_delete_validator_blocks_locked_item(self, full_feature_app):
        """Test that delete_validator blocks deletion of locked items"""
        app, _ = full_feature_app
        with TestClient(app) as client:
            res = client.post(
                "/items", json={"name": "Locked", "price": 10.0, "is_locked": True}
            )
            item_id = res.json()["id"]

            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 400
            assert "locked" in res.json()["detail"].lower()
