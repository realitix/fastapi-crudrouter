# pylint: disable=import-outside-toplevel,protected-access,reimported
# ruff: noqa: PLC0415
"""
Tests for Starlette path type converters in CRUDRouter.

Ensures that path converters (/:int, /:uuid, /:str) prevent route conflicts
and provide proper type validation at the routing level.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from fastapi_crudrouter import CRUDRouter

# Test models with int PK
Base = declarative_base()


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)


class ItemSchema(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class ItemCreate(BaseModel):
    name: str


class ItemUpdate(BaseModel):
    name: str | None = None


@pytest.fixture(scope="function")
def test_app_with_int_pk():
    """Create test app with int primary key and custom /deleted route."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

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

    return app, SessionLocal


class TestPathConvertersIntPK:
    """Test path converters with int primary key."""

    def test_int_pk_matches_numbers(self, test_app_with_int_pk):
        """Test that /{item_id:int} matches numeric IDs."""
        app, SessionLocal = test_app_with_int_pk

        # Create an item
        db = SessionLocal()
        item = Item(id=1, name="Test Item")
        db.add(item)
        db.commit()
        db.close()

        with TestClient(app) as client:
            # Numeric ID should match /{item_id:int}
            response = client.get("/items/1")
            assert response.status_code == 200
            assert response.json()["id"] == 1

    def test_int_pk_rejects_non_numeric_strings(self, test_app_with_int_pk):
        """Test that /{item_id:int} does NOT match non-numeric strings."""
        app, SessionLocal = test_app_with_int_pk

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
        app, SessionLocal = test_app_with_int_pk

        with TestClient(app) as client:
            # Custom /deleted route should be accessible
            response = client.get("/items/deleted")
            assert response.status_code == 200
            assert "message" in response.json()

            # Numeric routes should still work
            db = SessionLocal()
            item = Item(id=999, name="Another Item")
            db.add(item)
            db.commit()
            db.close()

            response = client.get("/items/999")
            assert response.status_code == 200
            assert response.json()["id"] == 999

    def test_invalid_numeric_id_returns_404(self, test_app_with_int_pk):
        """Test that non-existent numeric ID returns 404."""
        app, SessionLocal = test_app_with_int_pk

        with TestClient(app) as client:
            # Valid numeric format but non-existent item
            response = client.get("/items/99999")
            assert response.status_code == 404


class TestPathConverterMapping:
    """Test _get_path_converter() mapping logic."""

    def test_int_type_maps_to_int_converter(self):
        """Test that int type maps to 'int' converter."""
        from fastapi_crudrouter import CRUDRouter

        # Create a minimal router to test the method
        class DummyModel:
            __tablename__ = "dummy"
            __table__ = type(
                "Table",
                (),
                {
                    "primary_key": type(
                        "PK",
                        (),
                        {"columns": type("Cols", (), {"keys": lambda: ["id"]})()},
                    )()
                },
            )()

        class DummySchema(BaseModel):
            id: int

        def dummy_db():
            yield None

        router = CRUDRouter(
            schema=DummySchema,
            create_schema=DummySchema,
            db_model=DummyModel,
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

        class DummyModel:
            __tablename__ = "dummy"
            __table__ = type(
                "Table",
                (),
                {
                    "primary_key": type(
                        "PK",
                        (),
                        {"columns": type("Cols", (), {"keys": lambda: ["id"]})()},
                    )()
                },
            )()

        class DummySchema(BaseModel):
            id: str

        def dummy_db():
            yield None

        router = CRUDRouter(
            schema=DummySchema,
            create_schema=DummySchema,
            db_model=DummyModel,
            db=dummy_db,
            get_all_route=False,
            get_one_route=False,
            create_route=False,
            update_route=False,
            delete_one_route=False,
        )

        assert router._get_path_converter() == "str"
