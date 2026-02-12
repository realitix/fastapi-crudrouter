"""Tests for custom_func_fields priority in get_fields.

Verifies that callable metadata is correctly identified as custom_func_fields
even when the field annotation is a List type (which would previously be
incorrectly treated as join_list_fields).
"""

import asyncio
from typing import Annotated, List

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
import pytest
from sqlalchemy import Column, Float, Integer, String, func
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


class TestCustomFuncFieldsScalar:
    """Test custom_func_fields with scalar return types (basic case)."""

    @pytest.fixture
    def custom_func_app(self):
        """Create app with a scalar custom_func_field."""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_custom_func.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            def add_double_price(query):
                return query.add_columns(
                    (ItemModel.price * 2).label("double_price")
                )

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                price: float

            class ItemGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                price: float
                double_price: Annotated[float, add_double_price]

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                get_all_schema=ItemGetAllSchema,
                prefix="items",
            )
            app.include_router(router)
            return app, ItemGetAllSchema, router

        return run_async(_setup())

    def test_scalar_custom_func_field_categorized(self, custom_func_app):
        """Test that scalar callable is categorized as custom_func_field."""
        _app, schema, router = custom_func_app
        _, _, join_list_fields, custom_func_fields = router.get_fields(schema)
        assert "double_price" in custom_func_fields
        assert "double_price" not in join_list_fields

    def test_scalar_custom_func_field_get_all(self, custom_func_app):
        """Test that scalar custom_func_field works in get_all."""
        app, _, _ = custom_func_app
        with TestClient(app) as client:
            client.post("/items", json={"name": "Widget", "price": 25.0})
            res = client.get("/items")
            assert res.status_code == 200
            data = res.json()["data"]
            assert len(data) == 1
            assert data[0]["double_price"] == 50.0

    def test_scalar_custom_func_field_multiple_items(self, custom_func_app):
        """Test custom_func_field with multiple items."""
        app, _, _ = custom_func_app
        with TestClient(app) as client:
            client.post("/items", json={"name": "A", "price": 10.0})
            client.post("/items", json={"name": "B", "price": 20.0})
            client.post("/items", json={"name": "C", "price": 30.0})
            res = client.get("/items")
            assert res.status_code == 200
            data = res.json()["data"]
            prices = {d["name"]: d["double_price"] for d in data}
            assert prices["A"] == 20.0
            assert prices["B"] == 40.0
            assert prices["C"] == 60.0


class TestCustomFuncFieldsListType:
    """Test that callable metadata with List type annotation is correctly
    categorized as custom_func_field, not join_list_field.

    This is the core bug fix: previously, a field like
        tags: Annotated[List[str], some_callable]
    would be treated as join_list_field because the List check came first.
    """

    @pytest.fixture
    def list_custom_func_app(self):
        """Create app with a List-typed custom_func_field."""

        async def _setup():
            app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_custom_func_list.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            def add_item_count(query):
                return query.add_columns(
                    func.count().over().label("item_count")
                )

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                price: float

            # Schema with a List-typed field and callable metadata
            # This previously crashed with:
            #   TypeError: 'function' object is not subscriptable
            class ItemGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                price: float
                item_count: Annotated[int, add_item_count]

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                get_all_schema=ItemGetAllSchema,
                prefix="items",
            )
            app.include_router(router)
            return app, ItemGetAllSchema, router, add_item_count

        return run_async(_setup())

    def test_list_type_callable_categorized_as_custom_func(
        self, list_custom_func_app
    ):
        """Test that a callable is categorized as custom_func_field
        and not as join_list_field, regardless of field annotation type."""
        _app, schema, router, _func = list_custom_func_app
        _, _, join_list_fields, custom_func_fields = router.get_fields(schema)
        assert "item_count" in custom_func_fields
        assert "item_count" not in join_list_fields


class TestCustomFuncFieldsListAnnotation:
    """Test that a callable with an actual List annotation is treated
    as custom_func_field and the router can be created without crashing."""

    def test_router_creation_with_list_annotated_callable(self):
        """Verify router creation does not crash when schema has
        Annotated[List[...], callable].

        Before the fix, this would raise:
            TypeError: 'function' object is not subscriptable
        because the code tried to do callable[0] and callable[1].
        """

        async def _setup():
            _app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_list_annotated_callable.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)
                price = Column(Float)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            def add_tags_query(query):
                # Just a no-op custom func for testing categorization
                return query

            class ItemSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                price: float

            class ItemGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                price: float
                tags: Annotated[List[str], add_tags_query] = []

            class ItemCreateSchema(BaseModel):
                name: str
                price: float

            # This should NOT raise TypeError
            router = CRUDRouter(
                schema=ItemSchema,
                db_model=ItemModel,
                db=get_session,
                create_schema=ItemCreateSchema,
                get_all_schema=ItemGetAllSchema,
                prefix="items",
            )

            _, _, join_list, custom_func = router.get_fields(
                ItemGetAllSchema
            )
            return join_list, custom_func

        join_list, custom_func = run_async(_setup())
        assert "tags" in custom_func
        assert "tags" not in join_list

    def test_get_fields_callable_priority_over_list(self):
        """Verify get_fields checks callable before list type."""

        async def _setup():
            _app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_callable_priority.db"
            )

            class ItemModel(Base):
                __tablename__ = "items"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            def custom_query_modifier(query):
                return query

            class SubItem(BaseModel):
                value: str

            class SchemaWithListCallable(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                computed_list: Annotated[
                    List[SubItem], custom_query_modifier
                ] = []

            class CreateSchema(BaseModel):
                name: str

            router = CRUDRouter(
                schema=SchemaWithListCallable,
                db_model=ItemModel,
                db=get_session,
                create_schema=CreateSchema,
                get_all_schema=SchemaWithListCallable,
                prefix="items",
            )

            _, _, join_list, custom_func = router.get_fields(
                SchemaWithListCallable
            )
            return join_list, custom_func

        join_list, custom_func = run_async(_setup())
        assert "computed_list" in custom_func
        assert "computed_list" not in join_list


class TestJoinListFieldsStillWork:
    """Verify that join_list_fields with tuple metadata still work
    correctly after the priority change."""

    def test_tuple_metadata_with_list_type_is_join_list(self):
        """A List field with tuple metadata should still be join_list_field."""

        async def _setup():
            _app, engine, Base, get_session = await create_test_app_base(
                "sqlite+aiosqlite:///./test_join_list_still_works.db"
            )

            class ParentModel(Base):
                __tablename__ = "parents"
                id = Column(Integer, primary_key=True, index=True)
                name = Column(String)

            class ChildModel(Base):
                __tablename__ = "children"
                id = Column(Integer, primary_key=True, index=True)
                parent_id = Column(Integer)
                value = Column(String)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ChildSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                parent_id: int
                value: str

            class ParentSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str

            # Tuple metadata: (table, foreign_key) -> join_list_field
            class ParentGetAllSchema(BaseModel):
                model_config = ConfigDict(from_attributes=True)
                id: int
                name: str
                children: Annotated[
                    List[ChildSchema],
                    (ChildModel, ChildModel.parent_id),
                ] = []

            class ParentCreateSchema(BaseModel):
                name: str

            router = CRUDRouter(
                schema=ParentSchema,
                db_model=ParentModel,
                db=get_session,
                create_schema=ParentCreateSchema,
                get_all_schema=ParentGetAllSchema,
                prefix="parents",
            )

            _, _, join_list, custom_func = router.get_fields(
                ParentGetAllSchema
            )
            return join_list, custom_func

        join_list, custom_func = run_async(_setup())
        assert "children" in join_list
        assert "children" not in custom_func
