"""Tests for lifecycle hooks (after_create, after_update, after_delete)."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Column, Float, Integer, String
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


class TestLifecycleHooks:
    """Tests for lifecycle hooks (after_create, after_update, after_delete)"""

    @pytest.fixture
    def hooks_app(self):
        """Create app with lifecycle hooks"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_hooks.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            hook_tracker = {"after_create": [], "after_update": [], "after_delete": []}

            async def after_create_hook(model, user, db):
                hook_tracker["after_create"].append(
                    {"id": model.id, "name": model.name}
                )

            async def after_update_hook(model, user, db):
                hook_tracker["after_update"].append(
                    {"id": model.id, "name": model.name}
                )

            async def after_delete_hook(item_id, user, db):
                hook_tracker["after_delete"].append({"id": item_id})

            class ItemSchema(BaseModel):
                id: int
                name: str
                price: float
                quantity: int = 0

                class Config:
                    from_attributes = True

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                update_schema=ItemCreateSchema,
                prefix="items",
                after_create=after_create_hook,
                after_update=after_update_hook,
                after_delete=after_delete_hook,
            )
            app.include_router(router)
            return app, hook_tracker

        return run_async(_setup())

    def test_after_create_hook_called(self, hooks_app):
        """Test that after_create hook is called after creating item"""
        app, hook_tracker = hooks_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Test Item", "price": 10.0})
            assert res.status_code == 201

            assert len(hook_tracker["after_create"]) == 1
            assert hook_tracker["after_create"][0]["name"] == "Test Item"

    def test_after_update_hook_called_on_put(self, hooks_app):
        """Test that after_update hook is called after PUT update"""
        app, hook_tracker = hooks_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Original", "price": 10.0})
            item_id = res.json()["id"]

            res = client.put(
                f"/items/{item_id}",
                json={"name": "Updated", "price": 20.0},
            )
            assert res.status_code == 200

            assert len(hook_tracker["after_update"]) == 1
            assert hook_tracker["after_update"][0]["name"] == "Updated"

    def test_after_update_hook_called_on_patch(self, hooks_app):
        """Test that after_update hook is called after PATCH update"""
        app, hook_tracker = hooks_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Original", "price": 10.0})
            item_id = res.json()["id"]

            res = client.patch(f"/items/{item_id}", json={"name": "Patched"})
            assert res.status_code == 200

            assert len(hook_tracker["after_update"]) == 1
            assert hook_tracker["after_update"][0]["name"] == "Patched"

    def test_after_delete_hook_called(self, hooks_app):
        """Test that after_delete hook is called after deleting item"""
        app, hook_tracker = hooks_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "To Delete", "price": 10.0})
            item_id = res.json()["id"]

            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 204

            assert len(hook_tracker["after_delete"]) == 1
            assert hook_tracker["after_delete"][0]["id"] == item_id


class TestHookErrorHandling:
    """Test that hook errors don't fail the main operation"""

    def test_hook_error_does_not_fail_operation(self):
        """Test that hook errors don't fail the main operation"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_hooks_error.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async def failing_hook(model, user, db):
                raise Exception("Hook failed!")

            class ItemSchema(BaseModel):
                id: int
                name: str
                price: float
                quantity: int = 0

                class Config:
                    from_attributes = True

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                after_create=failing_hook,
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            # Create should succeed even if hook fails
            res = client.post("/items", json={"name": "Test", "price": 10.0})
            assert res.status_code == 201
