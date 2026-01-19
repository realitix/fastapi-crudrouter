"""Tests for default_order_by feature and OrderByBuilder."""

import asyncio
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from sqlalchemy import Column, Float, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy_utils import create_database, database_exists, drop_database

from fastapi_crudrouter import CRUDRouter
from fastapi_crudrouter.filtering import OrderByBuilder
from fastapi_crudrouter.logging import CRUDLogger


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


class TestDefaultOrderBy:
    """Tests for default_order_by feature"""

    @pytest.fixture
    def default_order_app(self):
        """Create app with default_order_by ASC"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_default_order.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)
                display_order = Column(Integer, default=0)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                id: int
                name: str
                price: float
                quantity: int = 0
                display_order: int = 0

                class Config:
                    from_attributes = True

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0
                display_order: int = 0

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                default_order_by="display_order",
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    @pytest.fixture
    def default_order_desc_app(self):
        """Create app with default_order_by DESC"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_default_order_desc.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

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
                default_order_by="price__DESC",
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_default_order_by_asc(self, default_order_app):
        """Test that items are ordered by display_order ASC by default"""
        app = default_order_app
        with TestClient(app) as client:
            client.post(
                "/items",
                json={"name": "Item C", "price": 30.0, "display_order": 3},
            )
            client.post(
                "/items",
                json={"name": "Item A", "price": 10.0, "display_order": 1},
            )
            client.post(
                "/items",
                json={"name": "Item B", "price": 20.0, "display_order": 2},
            )

            res = client.get("/items")
            assert res.status_code == 200
            data = res.json()["data"]

            assert len(data) == 3
            assert data[0]["display_order"] == 1
            assert data[1]["display_order"] == 2
            assert data[2]["display_order"] == 3

    def test_default_order_by_desc(self, default_order_desc_app):
        """Test that items are ordered by price DESC by default"""
        app = default_order_desc_app
        with TestClient(app) as client:
            client.post("/items", json={"name": "Cheap", "price": 10.0})
            client.post("/items", json={"name": "Medium", "price": 50.0})
            client.post("/items", json={"name": "Expensive", "price": 100.0})

            res = client.get("/items")
            assert res.status_code == 200
            data = res.json()["data"]

            assert len(data) == 3
            assert data[0]["price"] == 100.0
            assert data[1]["price"] == 50.0
            assert data[2]["price"] == 10.0

    def test_explicit_order_by_overrides_default(self, default_order_app):
        """Test that explicit order_by parameter overrides default"""
        app = default_order_app
        with TestClient(app) as client:
            client.post(
                "/items",
                json={"name": "Item C", "price": 30.0, "display_order": 3},
            )
            client.post(
                "/items",
                json={"name": "Item A", "price": 10.0, "display_order": 1},
            )
            client.post(
                "/items",
                json={"name": "Item B", "price": 20.0, "display_order": 2},
            )

            res = client.get("/items", params={"order_by": "price__DESC"})
            assert res.status_code == 200
            data = res.json()["data"]

            assert len(data) == 3
            assert data[0]["price"] == 30.0
            assert data[1]["price"] == 20.0
            assert data[2]["price"] == 10.0


class TestOrderByBuilderUnit:
    """Unit tests for OrderByBuilder with default_order_by parameter"""

    def test_default_order_by_initialization(self):
        """Test OrderByBuilder initialization with default_order_by"""
        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "test"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            display_order = Column(Integer)

        builder = OrderByBuilder(TestModel, "id", "display_order")
        assert builder.default_order_by == "display_order"

    def test_default_order_by_used_when_no_param(self):
        """Test that default_order_by is used when no order_by param"""
        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "test"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            display_order = Column(Integer)

        builder = OrderByBuilder(TestModel, "id", "display_order")
        result = builder.get_order_by(None)
        assert result is not None

    def test_default_order_by_desc(self):
        """Test default_order_by with DESC direction"""
        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "test"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            created_at = Column(String)

        builder = OrderByBuilder(TestModel, "id", "created_at__DESC")
        result = builder.get_order_by(None)
        assert result is not None

    def test_explicit_order_by_overrides_default(self):
        """Test that explicit order_by overrides default_order_by"""
        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "test"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            display_order = Column(Integer)

        builder = OrderByBuilder(TestModel, "id", "display_order")
        result = builder.get_order_by("name__DESC")
        assert result is not None

    def test_no_default_order_by_uses_pk_desc(self):
        """Test that without default_order_by, pk DESC is used"""
        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "test"
            id = Column(Integer, primary_key=True)
            name = Column(String)

        builder = OrderByBuilder(TestModel, "id")
        assert builder.default_order_by is None
        result = builder.get_order_by(None)
        assert result is not None


class TestCRUDLoggerError:
    """Tests for CRUDLogger.error method"""

    def test_error_method_logs_message(self):
        """Test that error method logs the message"""
        logger = CRUDLogger("TestModel")

        with patch.object(logger.logger, "error") as mock_error:
            logger.error("Test error message")
            mock_error.assert_called_once()
            call_args = mock_error.call_args
            assert call_args[0][0] == "Test error message"
            assert call_args[1]["extra"]["model"] == "TestModel"

    def test_error_method_with_special_characters(self):
        """Test error method with special characters in message"""
        logger = CRUDLogger("TestModel")

        with patch.object(logger.logger, "error") as mock_error:
            logger.error("Error: 'value' contains \"quotes\" and special chars: %s")
            mock_error.assert_called_once()
