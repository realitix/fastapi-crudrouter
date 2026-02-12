"""Tests for bulk operations (create, update, delete)."""

import asyncio
from typing import Any

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
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestBulkCreate:
    """Tests for bulk create operation"""

    @pytest.fixture
    def bulk_create_app(self):
        """Create app with bulk create enabled"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_create.db"
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
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                quantity: int = 0

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
                bulk_create_route=True,
                bulk_max_items=10,
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_bulk_create_multiple_items(self, bulk_create_app):
        """Test creating multiple items in one request"""
        app = bulk_create_app
        with TestClient(app) as client:
            items = [
                {"name": "Item 1", "price": 10.0},
                {"name": "Item 2", "price": 20.0},
                {"name": "Item 3", "price": 30.0},
            ]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 201

            data = res.json()
            assert data["success_count"] == 3
            assert data["error_count"] == 0
            assert len(data["created"]) == 3

    def test_bulk_create_exceeds_max_items(self, bulk_create_app):
        """Test that exceeding max items returns error"""
        app = bulk_create_app
        with TestClient(app) as client:
            items = [{"name": f"Item {i}", "price": float(i)} for i in range(11)]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 400
            assert "Maximum allowed" in res.json()["detail"]

    def test_bulk_create_empty_list(self, bulk_create_app):
        """Test bulk create with empty list"""
        app = bulk_create_app
        with TestClient(app) as client:
            res = client.post("/items/bulk", json=[])
            assert res.status_code == 201
            data = res.json()
            assert data["success_count"] == 0
            assert data["error_count"] == 0


class TestBulkUpdate:
    """Tests for bulk update operation"""

    @pytest.fixture
    def bulk_update_app(self):
        """Create app with bulk update enabled"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_update.db"
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
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                quantity: int = 0

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
                bulk_update_route=True,
                bulk_max_items=10,
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_bulk_update_multiple_items(self, bulk_update_app):
        """Test updating multiple items in one request"""
        app = bulk_update_app
        with TestClient(app) as client:
            # Create items first
            ids = []
            for i in range(3):
                res = client.post(
                    "/items", json={"name": f"Item {i}", "price": float(i * 10)}
                )
                ids.append(res.json()["id"])

            # Bulk update
            updates = [
                {"id": ids[0], "name": "Updated 1"},
                {"id": ids[1], "price": 99.99},
                {"id": ids[2], "name": "Updated 3", "quantity": 50},
            ]

            res = client.patch("/items/bulk", json=updates)
            assert res.status_code == 200

            data = res.json()
            assert data["success_count"] == 3
            assert data["error_count"] == 0

    def test_bulk_update_nonexistent_item(self, bulk_update_app):
        """Test bulk update with nonexistent item"""
        app = bulk_update_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Item 1", "price": 10.0})
            item_id = res.json()["id"]

            updates = [
                {"id": item_id, "name": "Updated"},
                {"id": 9999, "name": "Nonexistent"},
            ]

            res = client.patch("/items/bulk", json=updates)
            assert res.status_code == 200

            data = res.json()
            assert data["success_count"] == 1
            assert data["error_count"] == 1

    def test_bulk_update_exceeds_max_items(self, bulk_update_app):
        """Test that exceeding max items returns error"""
        app = bulk_update_app
        with TestClient(app) as client:
            updates = [{"id": i, "name": f"Item {i}"} for i in range(11)]

            res = client.patch("/items/bulk", json=updates)
            assert res.status_code == 400


class TestBulkDelete:
    """Tests for bulk delete operation"""

    @pytest.fixture
    def bulk_delete_app(self):
        """Create app with bulk delete enabled"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_delete.db"
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
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                quantity: int = 0

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
                bulk_delete_route=True,
                bulk_max_items=10,
            )
            app.include_router(router)
            return app

        return run_async(_setup())

    def test_bulk_delete_multiple_items(self, bulk_delete_app):
        """Test deleting multiple items in one request"""
        app = bulk_delete_app
        with TestClient(app) as client:
            ids = []
            for i in range(3):
                res = client.post(
                    "/items", json={"name": f"Item {i}", "price": float(i * 10)}
                )
                ids.append(res.json()["id"])

            res = client.get("/items")
            assert len(res.json()["data"]) == 3

            res = client.request("DELETE", "/items/bulk", json=ids)
            assert res.status_code == 200

            data = res.json()
            assert data["success_count"] == 3
            assert data["error_count"] == 0
            assert len(data["deleted_ids"]) == 3

            res = client.get("/items")
            assert len(res.json()["data"]) == 0

    def test_bulk_delete_nonexistent_items(self, bulk_delete_app):
        """Test bulk delete with nonexistent items"""
        app = bulk_delete_app
        with TestClient(app) as client:
            res = client.post("/items", json={"name": "Item 1", "price": 10.0})
            item_id = res.json()["id"]

            ids = [item_id, 9999]

            res = client.request("DELETE", "/items/bulk", json=ids)
            assert res.status_code == 200

            data = res.json()
            assert data["success_count"] == 1
            assert data["error_count"] == 1

    def test_bulk_delete_exceeds_max_items(self, bulk_delete_app):
        """Test that exceeding max items returns error"""
        app = bulk_delete_app
        with TestClient(app) as client:
            ids = list(range(11))

            res = client.request("DELETE", "/items/bulk", json=ids)
            assert res.status_code == 400

    def test_bulk_delete_with_soft_delete(self):
        """Test bulk delete with soft delete enabled"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_delete_soft.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)
                is_deleted = Column(Boolean, default=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                quantity: int = 0
                is_deleted: bool = False

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
                bulk_delete_route=True,
                soft_delete=True,
                soft_delete_field="is_deleted",
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            ids = []
            for i in range(2):
                res = client.post(
                    "/items", json={"name": f"Item {i}", "price": float(i * 10)}
                )
                ids.append(res.json()["id"])

            res = client.request("DELETE", "/items/bulk", json=ids)
            assert res.status_code == 200

            res = client.get("/items")
            assert len(res.json()["data"]) == 0

            res = client.get("/items", params={"include_deleted": True})
            assert len(res.json()["data"]) == 2

    def test_bulk_delete_with_delete_validator(self):
        """Test bulk delete with delete_validator enabled"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_delete_validator.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                quantity = Column(Integer, default=0)
                is_protected = Column(Boolean, default=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async def delete_validator(item_id: int, user: Any, db) -> None:
                item = await db.get(ItemModel, item_id)
                if item and item.is_protected:
                    raise HTTPException(400, f"Item {item_id} is protected")

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                quantity: int = 0
                is_protected: bool = False

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                quantity: int = 0
                is_protected: bool = False

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                bulk_delete_route=True,
                delete_validator=delete_validator,
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            res1 = client.post("/items", json={"name": "Normal", "price": 10.0})
            res2 = client.post(
                "/items",
                json={"name": "Protected", "price": 20.0, "is_protected": True},
            )
            id1 = res1.json()["id"]
            id2 = res2.json()["id"]

            res = client.request("DELETE", "/items/bulk", json=[id1, id2])
            assert res.status_code == 200

            data = res.json()
            assert data["success_count"] == 1
            assert data["error_count"] == 1
            assert "protected" in data["errors"][0]["error"].lower()


class TestBulkPartialSuccess:
    """Test bulk operations with partial_success setting"""

    def test_bulk_partial_success_false(self):
        """Test bulk operations with partial_success=False (atomic mode)"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_atomic.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String, unique=True)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                bulk_create_route=True,
                bulk_partial_success=False,
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            client.post("/items", json={"name": "Existing", "price": 10.0})

            items = [
                {"name": "New1", "price": 20.0},
                {"name": "Existing", "price": 30.0},  # Duplicate
                {"name": "New2", "price": 40.0},
            ]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 400

            res = client.get("/items")
            assert len(res.json()["data"]) == 1


class TestBulkCreateValidator:
    """Tests for bulk_create_validator parameter"""

    def test_bulk_create_validator_passes(self):
        """Test bulk create with validator that passes"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_validator_pass.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async def bulk_validator(items: list, user: Any, db) -> None:
                # Validator that always passes
                pass

            def get_current_user():
                return {"id": 1, "name": "Test User"}

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                bulk_create_route=True,
                bulk_create_validator=bulk_validator,
                current_user_dependency=get_current_user,
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            items = [
                {"name": "Item 1", "price": 10.0},
                {"name": "Item 2", "price": 20.0},
            ]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 201

            data = res.json()
            assert data["success_count"] == 2
            assert data["error_count"] == 0

    def test_bulk_create_validator_rejects_batch(self):
        """Test bulk create with validator that rejects the batch"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_validator_reject.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async def bulk_validator(items: list, user: Any, db) -> None:
                # Reject if total price exceeds 100
                total_price = sum(item.get("price", 0) for item in items)
                if total_price > 100:
                    raise HTTPException(
                        400, f"Total price {total_price} exceeds limit of 100"
                    )

            def get_current_user():
                return {"id": 1, "name": "Test User"}

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                bulk_create_route=True,
                bulk_create_validator=bulk_validator,
                current_user_dependency=get_current_user,
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            # Items with total price > 100 should be rejected
            items = [
                {"name": "Item 1", "price": 60.0},
                {"name": "Item 2", "price": 50.0},  # Total = 110
            ]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 400
            assert "exceeds limit" in res.json()["detail"]

            # Verify no items were created
            res = client.get("/items")
            assert len(res.json()["data"]) == 0

    def test_bulk_create_validator_receives_correct_data(self):
        """Test that validator receives items as list of dicts"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_validator_data.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)
                category = Column(String, default="default")

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            received_items = []

            async def bulk_validator(items: list, user: Any, db) -> None:
                # Store received items for verification
                received_items.extend(items)
                # Validate each item is a dict with expected keys
                for item in items:
                    if not isinstance(item, dict):
                        raise HTTPException(400, "Item is not a dict")
                    if "name" not in item or "price" not in item:
                        raise HTTPException(400, "Missing required fields")

            def get_current_user():
                return {"id": 1, "name": "Test User"}

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float
                category: str = "default"

            class ItemCreateSchema(BaseModel):
                name: str
                price: float
                category: str = "default"

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                bulk_create_route=True,
                bulk_create_validator=bulk_validator,
                current_user_dependency=get_current_user,
            )
            app.include_router(router)
            return app, received_items

        app, received_items = run_async(_setup())
        with TestClient(app) as client:
            items = [
                {"name": "Item 1", "price": 10.0},
                {"name": "Item 2", "price": 20.0, "category": "special"},
            ]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 201

            # Verify validator received correct data
            assert len(received_items) == 2
            assert received_items[0]["name"] == "Item 1"
            assert received_items[0]["price"] == 10.0
            assert received_items[1]["name"] == "Item 2"
            assert received_items[1]["category"] == "special"

    def test_bulk_create_validator_with_duplicate_names(self):
        """Test validator rejecting duplicates in batch"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_validator_duplicates.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async def bulk_validator(items: list, user: Any, db) -> None:
                # Check for duplicate names in batch
                names = [item.get("name") for item in items]
                if len(names) != len(set(names)):
                    raise HTTPException(400, "Duplicate names found in batch")

            def get_current_user():
                return {"id": 1, "name": "Test User"}

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                bulk_create_route=True,
                bulk_create_validator=bulk_validator,
                current_user_dependency=get_current_user,
            )
            app.include_router(router)
            return app

        app = run_async(_setup())
        with TestClient(app) as client:
            # Batch with duplicate names
            items = [
                {"name": "Item 1", "price": 10.0},
                {"name": "Item 1", "price": 20.0},  # Duplicate name
            ]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 400
            assert "Duplicate names" in res.json()["detail"]

            # Batch with unique names should pass
            items = [
                {"name": "Item 1", "price": 10.0},
                {"name": "Item 2", "price": 20.0},
            ]

            res = client.post("/items/bulk", json=items)
            assert res.status_code == 201

    def test_bulk_create_validator_not_called_without_user(self):
        """Test that validator is only called when user is present"""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_bulk_validator_no_user.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            validator_called = {"count": 0}

            async def bulk_validator(items: list, user: Any, db) -> None:
                validator_called["count"] += 1
                # This validator always rejects
                raise HTTPException(400, "Validator was called")

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)

                id: int
                name: str
                price: float

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            # Router WITHOUT get_current_user - validator should not be called
            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                prefix="items",
                bulk_create_route=True,
                bulk_create_validator=bulk_validator,
            )
            app.include_router(router)
            return app, validator_called

        app, validator_called = run_async(_setup())
        with TestClient(app) as client:
            items = [{"name": "Item 1", "price": 10.0}]

            res = client.post("/items/bulk", json=items)
            # Without user, validator is not called, so creation succeeds
            assert res.status_code == 201
            assert validator_called["count"] == 0
