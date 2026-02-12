# pylint: disable=import-outside-toplevel,protected-access,reimported
# ruff: noqa: PLC0415
"""
Tests for Starlette path type converters in CRUDRouter.

Ensures that path converters (/:int, /:uuid, /:str) prevent route conflicts
and provide proper type validation at the routing level.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import StaticPool

from fastapi_crudrouter import CRUDRouter

# Test models with int PK
Base = declarative_base()


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)


class ItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ItemCreate(BaseModel):
    name: str


class ItemUpdate(BaseModel):
    name: str | None = None


@pytest.fixture(scope="function")
def test_app_with_int_pk():
    """Create test app with int primary key and custom /deleted route."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        # Create async engine and tables synchronously
        async def _setup():
            engine = create_async_engine(
                "sqlite+aiosqlite:///:memory:",
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )

            # Create tables async
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            return engine

        engine = loop.run_until_complete(_setup())

        AsyncSessionLocal = async_sessionmaker(
            autocommit=False, autoflush=False, bind=engine
        )

        async def get_db():
            async with AsyncSessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app = FastAPI()

        # Add CRUDRouter (will use /{item_id:int})
        router = CRUDRouter(
            schema=ItemSchema,
            create_schema=ItemCreate,
            update_schema=ItemUpdate,
            db_model=Item,
            db=get_db,
            prefix="/items",
        )

        # Add custom /deleted route AFTER CRUDRouter
        # This should NOT conflict thanks to /{item_id:int}
        @router.get("/deleted")
        def list_deleted():
            return {"message": "deleted items", "items": []}

        app.include_router(router)

        yield app

        # Cleanup
        async def _cleanup():
            await engine.dispose()

        loop.run_until_complete(_cleanup())
    finally:
        loop.close()


class TestPathConvertersIntPK:
    """Test path converters with int primary key."""

    def test_int_pk_matches_numbers(self, test_app_with_int_pk):
        """Test that /{item_id:int} matches numeric IDs."""
        app = test_app_with_int_pk

        with TestClient(app) as client:
            # Create an item via POST request
            create_response = client.post("/items", json={"name": "Test Item"})
            assert create_response.status_code == 201
            item_id = create_response.json()["id"]

            # Numeric ID should match /{item_id:int}
            response = client.get(f"/items/{item_id}")
            assert response.status_code == 200
            assert response.json()["name"] == "Test Item"

    def test_int_pk_rejects_non_numeric_strings(self, test_app_with_int_pk):
        """Test that /{item_id:int} does NOT match non-numeric strings."""
        app = test_app_with_int_pk

        with TestClient(app) as client:
            # "deleted" should NOT match /{item_id:int}
            # Should route to /deleted endpoint instead
            response = client.get("/items/deleted")
            assert response.status_code == 200
            json_data = response.json()
            assert "message" in json_data
            assert json_data["message"] == "deleted items"

    def test_custom_route_no_conflict_with_int_pk(self, test_app_with_int_pk):
        """Test that custom routes like /deleted don't conflict with /{item_id:int}."""
        app = test_app_with_int_pk

        with TestClient(app) as client:
            # Custom /deleted route should be accessible
            response = client.get("/items/deleted")
            assert response.status_code == 200
            assert "message" in response.json()

            # Create an item via POST request
            create_response = client.post("/items", json={"name": "Another Item"})
            assert create_response.status_code == 201
            item_id = create_response.json()["id"]

            # Numeric routes should still work
            response = client.get(f"/items/{item_id}")
            assert response.status_code == 200
            assert response.json()["name"] == "Another Item"

    def test_invalid_numeric_id_returns_404(self, test_app_with_int_pk):
        """Test that non-existent numeric ID returns 404."""
        app = test_app_with_int_pk

        with TestClient(app) as client:
            # Valid numeric format but non-existent item
            response = client.get("/items/99999")
            assert response.status_code == 404


class TestPathConverterMapping:
    """Test _get_path_converter() mapping logic."""

    def test_int_type_maps_to_int_converter(self):
        """Test that int type maps to 'int' converter."""
        from fastapi_crudrouter import CRUDRouter

        # Create a real SQLAlchemy model with int PK
        ModelBase = declarative_base()

        class IntPKModel(ModelBase):
            __tablename__ = "int_pk_test"
            id = Column(Integer, primary_key=True)

        class IntPKSchema(BaseModel):
            id: int

        async def dummy_db():
            yield None

        router = CRUDRouter(
            schema=IntPKSchema,
            create_schema=IntPKSchema,
            db_model=IntPKModel,
            db=dummy_db,
            get_all_route=False,
            get_one_route=False,
            create_route=False,
            update_route=False,
            delete_one_route=False,
        )

        # Test the mapping
        assert router._get_path_converter() == "int"

    def test_str_type_maps_to_str_converter(self):
        """Test that str type maps to 'str' converter."""
        from fastapi_crudrouter import CRUDRouter

        # Create a real SQLAlchemy model with str PK
        ModelBase = declarative_base()

        class StrPKModel(ModelBase):
            __tablename__ = "str_pk_test"
            id = Column(String, primary_key=True)

        class StrPKSchema(BaseModel):
            id: str

        async def dummy_db():
            yield None

        router = CRUDRouter(
            schema=StrPKSchema,
            create_schema=StrPKSchema,
            db_model=StrPKModel,
            db=dummy_db,
            get_all_route=False,
            get_one_route=False,
            create_route=False,
            update_route=False,
            delete_one_route=False,
        )

        assert router._get_path_converter() == "str"
