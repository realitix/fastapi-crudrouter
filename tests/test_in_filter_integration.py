"""Integration tests for IN filter with Enum fields"""

import asyncio
from enum import Enum
from typing import Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from sqlalchemy import Column, Float, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy_utils import create_database, database_exists, drop_database

from fastapi_crudrouter import CRUDRouter
from fastapi_crudrouter.schema_factory import create_filter


class Status(str, Enum):
    """Status enum for testing"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    ARCHIVED = "archived"


class ItemBase(BaseModel):
    """Base item schema"""

    name: str
    price: float
    status: Status


class Item(ItemBase):
    """Item schema with ID"""

    id: int

    class Config:
        orm_mode = True


class ItemFilter(BaseModel):
    """Filter schema for items"""

    name: Optional[str] = None
    status: Optional[Status] = None


# Create extended filter with __in support for enum fields
ItemFilterExtended = create_filter(ItemFilter)


@pytest.fixture(scope="module")
def in_filter_client():
    """Create a test client with an Item model that has an Enum field"""
    db_uri = "sqlite+aiosqlite:///./test_in_filter.db"
    sync_uri = db_uri.replace("+aiosqlite", "")

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

    class ItemModel(Base):
        __tablename__ = "items"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String)
        price = Column(Float)
        status = Column(String)

    # Create tables
    async def create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(create_tables())

    app.include_router(
        CRUDRouter(
            schema=Item,
            db_model=ItemModel,
            db=get_session,
            prefix="items",
            filter_schema=ItemFilterExtended,
            paginate=10,
        )
    )

    with TestClient(app) as client:
        yield client

    # Cleanup
    if database_exists(sync_uri):
        drop_database(sync_uri)


class TestInFilterIntegration:
    """Integration tests for IN filter with Enum fields"""

    def test_in_filter_with_single_enum_value(self, in_filter_client):
        """Test that __in filter works with a single enum value"""
        client = in_filter_client

        # Clean database
        client.delete("/items")

        # Create test data
        items = [
            {"name": "Item1", "price": 10.0, "status": "active"},
            {"name": "Item2", "price": 20.0, "status": "inactive"},
            {"name": "Item3", "price": 30.0, "status": "pending"},
        ]

        for item in items:
            res = client.post("/items", json=item)
            assert res.status_code == 201

        # Test filter with __in on status field (single value)
        res = client.get("/items", params={"status__in": "active"})
        assert res.status_code == 200

        data = res.json()
        items_data = data["data"] if isinstance(data, dict) and "data" in data else data

        assert len(items_data) == 1
        assert items_data[0]["status"] == "active"

    def test_in_filter_with_comma_separated_enum_values(self, in_filter_client):
        """Test that __in filter works with comma-separated enum values"""
        client = in_filter_client

        # Clean database
        client.delete("/items")

        # Create test data
        items = [
            {"name": "Item1", "price": 10.0, "status": "active"},
            {"name": "Item2", "price": 20.0, "status": "inactive"},
            {"name": "Item3", "price": 30.0, "status": "pending"},
            {"name": "Item4", "price": 40.0, "status": "archived"},
        ]

        for item in items:
            res = client.post("/items", json=item)
            assert res.status_code == 201

        # Test filter with __in on status field (comma-separated)
        res = client.get("/items", params={"status__in": "active,pending"})
        assert res.status_code == 200

        data = res.json()
        items_data = data["data"] if isinstance(data, dict) and "data" in data else data

        assert len(items_data) == 2
        statuses = {item["status"] for item in items_data}
        assert statuses == {"active", "pending"}

    def test_in_filter_with_spaces_in_comma_separated(self, in_filter_client):
        """Test that __in filter handles spaces in comma-separated values"""
        client = in_filter_client

        # Clean database
        client.delete("/items")

        # Create test data
        items = [
            {"name": "Item1", "price": 10.0, "status": "active"},
            {"name": "Item2", "price": 20.0, "status": "inactive"},
            {"name": "Item3", "price": 30.0, "status": "pending"},
        ]

        for item in items:
            res = client.post("/items", json=item)
            assert res.status_code == 201

        # Test filter with __in on status field (comma-separated with spaces)
        res = client.get("/items", params={"status__in": "inactive , pending"})
        assert res.status_code == 200

        data = res.json()
        items_data = data["data"] if isinstance(data, dict) and "data" in data else data

        assert len(items_data) == 2
        statuses = {item["status"] for item in items_data}
        assert statuses == {"inactive", "pending"}

    def test_in_filter_no_matches(self, in_filter_client):
        """Test that __in filter returns empty when no matches"""
        client = in_filter_client

        # Clean database
        client.delete("/items")

        # Create test data
        items = [
            {"name": "Item1", "price": 10.0, "status": "active"},
            {"name": "Item2", "price": 20.0, "status": "inactive"},
        ]

        for item in items:
            res = client.post("/items", json=item)
            assert res.status_code == 201

        # Test filter with __in on status field (no matching values)
        # Note: "archived" is a valid enum value but no items have it
        res = client.get("/items", params={"status__in": "archived"})
        assert res.status_code == 200

        data = res.json()
        items_data = data["data"] if isinstance(data, dict) and "data" in data else data

        assert len(items_data) == 0

    def test_in_filter_all_values(self, in_filter_client):
        """Test that __in filter with all enum values returns all items"""
        client = in_filter_client

        # Clean database
        client.delete("/items")

        # Create test data
        items = [
            {"name": "Item1", "price": 10.0, "status": "active"},
            {"name": "Item2", "price": 20.0, "status": "inactive"},
            {"name": "Item3", "price": 30.0, "status": "pending"},
        ]

        for item in items:
            res = client.post("/items", json=item)
            assert res.status_code == 201

        # Test filter with __in on status field (all values)
        res = client.get("/items", params={"status__in": "active,inactive,pending"})
        assert res.status_code == 200

        data = res.json()
        items_data = data["data"] if isinstance(data, dict) and "data" in data else data

        assert len(items_data) == 3

    def test_in_filter_combined_with_other_filters(self, in_filter_client):
        """Test that __in filter can be combined with other filters"""
        client = in_filter_client

        # Clean database
        client.delete("/items")

        # Create test data
        items = [
            {"name": "Apple", "price": 10.0, "status": "active"},
            {"name": "Banana", "price": 20.0, "status": "active"},
            {"name": "Cherry", "price": 30.0, "status": "inactive"},
        ]

        for item in items:
            res = client.post("/items", json=item)
            assert res.status_code == 201

        # Test filter with __in combined with name__like
        res = client.get(
            "/items", params={"status__in": "active,inactive", "name__like": "an"}
        )
        assert res.status_code == 200

        data = res.json()
        items_data = data["data"] if isinstance(data, dict) and "data" in data else data

        # Should return Banana (contains "an" and is active)
        assert len(items_data) == 1
        assert items_data[0]["name"] == "Banana"
