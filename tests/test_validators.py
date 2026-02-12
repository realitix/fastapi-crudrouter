"""Tests for validators (delete_validator, create_defaults)."""

import asyncio
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
import pytest
from sqlalchemy import Boolean, Column, Float, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
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
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class MockUser:
    """Mock user for testing"""

    def __init__(self, user_id: int = 1, school_id: int = 100, is_admin: bool = False):
        self.id = user_id
        self.school_id = school_id
        self.is_admin = is_admin


class TestDeleteValidator:
    """Tests for delete_validator feature"""

    @pytest.fixture
    def delete_validator_app(self):
        """Create app with delete_validator"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_delete_validator.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)
                is_default = Column(Boolean, default=False)
                has_children = Column(Boolean, default=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                quantity: int = 0
                is_default: bool = False
                has_children: bool = False

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0
                is_default: bool = False
                has_children: bool = False

            class ItemUpdateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0

            async def validate_delete(item_id: int, user: Any, db) -> None:
                """Prevent deletion of default or items with children"""
                item = await db.get(ItemModel, item_id)
                if item and item.is_default:
                    raise HTTPException(400, "Cannot delete default item")
                if item and item.has_children:
                    raise HTTPException(400, "Cannot delete item with children")

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                update_schema=ItemUpdateSchema,
                prefix="items",
                delete_validator=validate_delete,
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_delete_validator_allows_normal_deletion(self, delete_validator_app):
        """Test that normal items can be deleted"""
        app = delete_validator_app
        with TestClient(app) as client:
            res = client.post(
                "/items", json={"name": "Normal Item", "price": 10.0, "quantity": 5}
            )
            assert res.status_code == 201
            item_id = res.json()["id"]

            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 204

    def test_delete_validator_blocks_default_item(self, delete_validator_app):
        """Test that default items cannot be deleted"""
        app = delete_validator_app
        with TestClient(app) as client:
            res = client.post(
                "/items",
                json={
                    "name": "Default Item",
                    "price": 10.0,
                    "quantity": 5,
                    "is_default": True,
                },
            )
            assert res.status_code == 201
            item_id = res.json()["id"]

            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 400
            assert "Cannot delete default item" in res.json()["detail"]

    def test_delete_validator_blocks_items_with_children(self, delete_validator_app):
        """Test that items with children cannot be deleted"""
        app = delete_validator_app
        with TestClient(app) as client:
            res = client.post(
                "/items",
                json={
                    "name": "Parent Item",
                    "price": 10.0,
                    "quantity": 5,
                    "has_children": True,
                },
            )
            assert res.status_code == 201
            item_id = res.json()["id"]

            res = client.delete(f"/items/{item_id}")
            assert res.status_code == 400
            assert "Cannot delete item with children" in res.json()["detail"]


class TestCreateDefaults:
    """Tests for create_defaults feature"""

    @pytest.fixture
    def create_defaults_app(self):
        """Create app with create_defaults"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_create_defaults.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)
                school_id = Column(Integer, nullable=True)
                created_by_id = Column(Integer, nullable=True)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                quantity: int = 0
                school_id: Optional[int] = None
                created_by_id: Optional[int] = None

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0
                school_id: Optional[int] = None
                created_by_id: Optional[int] = None

            class ItemUpdateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0

            def get_current_user():
                return MockUser(user_id=42, school_id=123)

            def get_defaults(user: MockUser) -> dict:
                """Return defaults based on user context"""
                return {"school_id": user.school_id, "created_by_id": user.id}

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                update_schema=ItemUpdateSchema,
                prefix="items",
                current_user_dependency=get_current_user,
                create_defaults=get_defaults,
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_create_defaults_applied(self, create_defaults_app):
        """Test that defaults are applied from user context"""
        app = create_defaults_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Test Item", "price": 10.0})
            assert res.status_code == 201

            data = res.json()
            assert data["school_id"] == 123
            assert data["created_by_id"] == 42

    def test_create_defaults_explicit_values_override(self, create_defaults_app):
        """Test that explicit request values override defaults"""
        app = create_defaults_app
        with TestClient(app) as client:
            res = client.post(
                "/items",
                json={"name": "Test Item", "price": 10.0, "school_id": 999},
            )
            assert res.status_code == 201

            data = res.json()
            assert data["school_id"] == 999  # Explicit value
            assert data["created_by_id"] == 42  # Default applied


class TestCreateDefaultsWithNoUser:
    """Test create_defaults when user is None"""

    def test_create_defaults_with_no_user(self):
        """Test create_defaults when user is None"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_create_defaults_no_user.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                school_id = Column(Integer, nullable=True)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                school_id: Optional[int] = None

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                school_id: Optional[int] = None

            def get_defaults(user):
                if user:
                    return {"school_id": user.school_id}
                return {}

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                create_defaults=get_defaults,
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Test", "price": 10.0})
            assert res.status_code == 201
            assert res.json()["school_id"] is None
