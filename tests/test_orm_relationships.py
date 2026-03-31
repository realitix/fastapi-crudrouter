"""Tests for ORM relationship auto-detection and ORM mode queries.

Verifies that:
- RelationshipProperty fields (without Field metadata) trigger ORM mode
- selectinload is used for eager loading of relationships
- @property fields on the model trigger safety-net eager loading
- Nested relationships are loaded one level deep
- _fields_cache caches results per schema
- ORM mode and column mode produce correct results via get_one/get_all
"""

import asyncio
from typing import Annotated, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
import pytest
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy_utils import (
    create_database,
    database_exists,
    drop_database,
)

from fastapi_crudrouter import CRUDRouter


DB_URI = "sqlite+aiosqlite:///./test_orm_rel.db"


async def create_test_app_base():
    sync_uri = DB_URI.replace("+aiosqlite", "")
    if database_exists(sync_uri):
        drop_database(sync_uri)
    create_database(sync_uri)

    app = FastAPI()
    engine = create_async_engine(DB_URI)
    SessionLocal = async_sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    Base = declarative_base()

    async def get_session():
        async with SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    return app, engine, Base, get_session


# ------------------------------------------------------------------
# Test 1: Simple ORM relationship (Author -> Books)
# ------------------------------------------------------------------
class TestOrmRelationshipBasic:
    """ORM mode with a simple one-to-one relationship."""

    @pytest.fixture()
    def orm_app(self):
        loop = asyncio.new_event_loop()

        async def _build():
            app, engine, Base, get_session = (
                await create_test_app_base()
            )

            class CountryModel(Base):
                __tablename__ = "countries"
                id = Column(Integer, primary_key=True)
                name = Column(String)

            class AuthorModel(Base):
                __tablename__ = "authors"
                id = Column(Integer, primary_key=True)
                name = Column(String)
                country_id = Column(
                    Integer, ForeignKey("countries.id")
                )
                country = relationship(
                    "CountryModel", lazy="raise"
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # Seed data
            async with (
                async_sessionmaker(bind=engine)() as session
            ):
                c = CountryModel(id=1, name="France")
                session.add(c)
                await session.flush()
                a = AuthorModel(
                    id=1, name="Victor Hugo", country_id=1
                )
                session.add(a)
                await session.commit()

            class CountrySchema(BaseModel):
                id: int
                name: str
                model_config = ConfigDict(
                    from_attributes=True
                )

            class AuthorSchema(BaseModel):
                id: int
                name: str
                country: Optional[CountrySchema] = None
                model_config = ConfigDict(
                    from_attributes=True
                )

            class AuthorCreate(BaseModel):
                name: str
                country_id: int

            router = CRUDRouter(
                schema=AuthorSchema,
                create_schema=AuthorCreate,
                db_model=AuthorModel,
                db=get_session,
                prefix="authors",
            )
            app.include_router(router)
            return app, AuthorSchema, router

        result = loop.run_until_complete(_build())
        yield result
        loop.close()

    def test_get_fields_detects_relationship(self, orm_app):
        _app, schema, router = orm_app
        (
            base_fields,
            join_fields,
            join_list_fields,
            custom_func_fields,
            orm_rels,
            _has_props,
        ) = router.get_fields(schema)
        assert "country" in orm_rels
        assert len(join_fields) == 0
        assert len(custom_func_fields) == 0

    def test_build_base_query_orm_mode(self, orm_app):
        _app, schema, router = orm_app
        _query, _jlf, orm_mode = router._build_base_query(
            schema
        )
        assert orm_mode is True

    def test_get_all_returns_nested(self, orm_app):
        app, _schema, _router = orm_app
        client = TestClient(app)
        resp = client.get("/authors")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        author = data[0]
        assert author["name"] == "Victor Hugo"
        assert author["country"]["name"] == "France"

    def test_get_one_returns_nested(self, orm_app):
        app, _schema, _router = orm_app
        client = TestClient(app)
        resp = client.get("/authors/1")
        assert resp.status_code == 200
        author = resp.json()
        assert author["name"] == "Victor Hugo"
        assert author["country"]["name"] == "France"

    def test_fields_cache(self, orm_app):
        """get_fields called twice returns cached result."""
        _app, schema, router = orm_app
        result1 = router.get_fields(schema)
        result2 = router.get_fields(schema)
        assert result1 is result2


# ------------------------------------------------------------------
# Test 2: @property field triggers safety-net eager loading
# ------------------------------------------------------------------
class TestPropertyFieldEagerLoading:
    """@property on the model triggers eager loading of all
    non-collection relationships so async access doesn't raise
    MissingGreenlet."""

    @pytest.fixture()
    def property_app(self):
        loop = asyncio.new_event_loop()

        async def _build():
            app, engine, Base, get_session = (
                await create_test_app_base()
            )

            class PersonModel(Base):
                __tablename__ = "persons"
                id = Column(Integer, primary_key=True)
                first_name = Column(String)
                last_name = Column(String)

            class StudentModel(Base):
                __tablename__ = "students"
                id = Column(Integer, primary_key=True)
                person_id = Column(
                    Integer, ForeignKey("persons.id")
                )
                grade = Column(String)
                person = relationship(
                    "PersonModel", lazy="raise"
                )

                @property
                def full_name(self) -> str:
                    return (
                        f"{self.person.first_name}"
                        f" {self.person.last_name}"
                    )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with (
                async_sessionmaker(bind=engine)() as session
            ):
                p = PersonModel(
                    id=1,
                    first_name="Marie",
                    last_name="Curie",
                )
                session.add(p)
                await session.flush()
                s = StudentModel(
                    id=1, person_id=1, grade="A+"
                )
                session.add(s)
                await session.commit()

            class StudentSchema(BaseModel):
                id: int
                grade: str
                full_name: str
                model_config = ConfigDict(
                    from_attributes=True
                )

            class StudentCreate(BaseModel):
                person_id: int
                grade: str

            router = CRUDRouter(
                schema=StudentSchema,
                create_schema=StudentCreate,
                db_model=StudentModel,
                db=get_session,
                prefix="students",
            )
            app.include_router(router)
            return app, StudentSchema, router

        result = loop.run_until_complete(_build())
        yield result
        loop.close()

    def test_get_fields_detects_property(self, property_app):
        _app, schema, router = property_app
        (
            _base,
            _joins,
            _jlf,
            _cffs,
            orm_rels,
            has_props,
        ) = router.get_fields(schema)
        # @property triggers safety-net: all non-collection
        # relationships get loaded
        assert has_props is True
        assert "person" in orm_rels

    def test_get_all_with_property(self, property_app):
        app, _schema, _router = property_app
        client = TestClient(app)
        resp = client.get("/students")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["full_name"] == "Marie Curie"
        assert data[0]["grade"] == "A+"

    def test_get_one_with_property(self, property_app):
        app, _schema, _router = property_app
        client = TestClient(app)
        resp = client.get("/students/1")
        assert resp.status_code == 200
        student = resp.json()
        assert student["full_name"] == "Marie Curie"


# ------------------------------------------------------------------
# Test 3: Nested relationship loading (one level deep)
# ------------------------------------------------------------------
class TestNestedRelationshipLoading:
    """Verify that nested non-collection relationships are loaded
    one level deep via selectinload chaining."""

    @pytest.fixture()
    def nested_app(self):
        loop = asyncio.new_event_loop()

        async def _build():
            app, engine, Base, get_session = (
                await create_test_app_base()
            )

            class CityModel(Base):
                __tablename__ = "cities"
                id = Column(Integer, primary_key=True)
                name = Column(String)

            class CompanyModel(Base):
                __tablename__ = "companies"
                id = Column(Integer, primary_key=True)
                name = Column(String)
                city_id = Column(
                    Integer, ForeignKey("cities.id")
                )
                city = relationship(
                    "CityModel", lazy="raise"
                )

            class EmployeeModel(Base):
                __tablename__ = "employees"
                id = Column(Integer, primary_key=True)
                name = Column(String)
                company_id = Column(
                    Integer, ForeignKey("companies.id")
                )
                company = relationship(
                    "CompanyModel", lazy="raise"
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with (
                async_sessionmaker(bind=engine)() as session
            ):
                city = CityModel(id=1, name="Paris")
                session.add(city)
                await session.flush()
                comp = CompanyModel(
                    id=1, name="Acme", city_id=1
                )
                session.add(comp)
                await session.flush()
                emp = EmployeeModel(
                    id=1, name="Alice", company_id=1
                )
                session.add(emp)
                await session.commit()

            class CitySchema(BaseModel):
                id: int
                name: str
                model_config = ConfigDict(
                    from_attributes=True
                )

            class CompanySchema(BaseModel):
                id: int
                name: str
                city: Optional[CitySchema] = None
                model_config = ConfigDict(
                    from_attributes=True
                )

            class EmployeeSchema(BaseModel):
                id: int
                name: str
                company: Optional[CompanySchema] = None
                model_config = ConfigDict(
                    from_attributes=True
                )

            class EmployeeCreate(BaseModel):
                name: str
                company_id: int

            router = CRUDRouter(
                schema=EmployeeSchema,
                create_schema=EmployeeCreate,
                db_model=EmployeeModel,
                db=get_session,
                prefix="employees",
            )
            app.include_router(router)
            return app, EmployeeSchema, router

        result = loop.run_until_complete(_build())
        yield result
        loop.close()

    def test_nested_relationship_loaded(self, nested_app):
        app, _schema, _router = nested_app
        client = TestClient(app)
        resp = client.get("/employees")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        emp = data[0]
        assert emp["name"] == "Alice"
        assert emp["company"]["name"] == "Acme"
        # Nested city loaded one level deep
        assert emp["company"]["city"]["name"] == "Paris"

    def test_nested_get_one(self, nested_app):
        app, _schema, _router = nested_app
        client = TestClient(app)
        resp = client.get("/employees/1")
        assert resp.status_code == 200
        emp = resp.json()
        assert emp["company"]["city"]["name"] == "Paris"


# ------------------------------------------------------------------
# Test 4: ORM mode disabled when Field metadata exists
# ------------------------------------------------------------------
class TestOrmModeNotUsedWithMetadata:
    """When schema fields use Field(metadata=[...]), ORM mode should
    NOT activate even if relationships exist."""

    @pytest.fixture()
    def mixed_app(self):
        loop = asyncio.new_event_loop()

        async def _build():
            app, engine, Base, get_session = (
                await create_test_app_base()
            )

            class TagModel(Base):
                __tablename__ = "tags"
                id = Column(Integer, primary_key=True)
                label = Column(String)

            class ArticleModel(Base):
                __tablename__ = "articles"
                id = Column(Integer, primary_key=True)
                title = Column(String)
                tag_id = Column(
                    Integer, ForeignKey("tags.id")
                )
                tag = relationship(
                    "TagModel", lazy="raise"
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            class ArticleSchema(BaseModel):
                id: int
                title: str
                # Annotated metadata -> forces column mode
                tag_label: Annotated[
                    Optional[str], ArticleModel.tag
                ] = None
                model_config = ConfigDict(
                    from_attributes=True
                )

            class ArticleCreate(BaseModel):
                title: str
                tag_id: int

            router = CRUDRouter(
                schema=ArticleSchema,
                create_schema=ArticleCreate,
                db_model=ArticleModel,
                db=get_session,
                prefix="articles",
            )
            app.include_router(router)
            return app, ArticleSchema, router

        result = loop.run_until_complete(_build())
        yield result
        loop.close()

    def test_orm_mode_disabled_with_metadata(self, mixed_app):
        _app, schema, router = mixed_app
        _query, _jlf, orm_mode = router._build_base_query(
            schema
        )
        assert orm_mode is False

    def test_get_fields_has_join_fields(self, mixed_app):
        _app, schema, router = mixed_app
        (
            _base,
            join_fields,
            _jlf,
            _cffs,
            orm_rels,
            _has_props,
        ) = router.get_fields(schema)
        assert "tag_label" in join_fields
        # No auto-detected ORM relationships because
        # tag_label consumed the tag relationship via metadata
        assert len(orm_rels) == 0


# ------------------------------------------------------------------
# Test 5: Relationship with collection (uselist=True)
# ------------------------------------------------------------------
class TestCollectionRelationshipNotLoaded:
    """Collection relationships (uselist=True) should NOT be auto-
    loaded in safety-net mode for @property fields."""

    @pytest.fixture()
    def collection_app(self):
        loop = asyncio.new_event_loop()

        async def _build():
            app, engine, Base, get_session = (
                await create_test_app_base()
            )

            class ParentModel(Base):
                __tablename__ = "parents_coll"
                id = Column(Integer, primary_key=True)
                name = Column(String)
                children = relationship(
                    "ChildModel",
                    back_populates="parent",
                    lazy="raise",
                )

                @property
                def label(self) -> str:
                    return f"Parent: {self.name}"

            class ChildModel(Base):
                __tablename__ = "children_coll"
                id = Column(Integer, primary_key=True)
                parent_id = Column(
                    Integer, ForeignKey("parents_coll.id")
                )
                parent = relationship(
                    "ParentModel",
                    back_populates="children",
                    lazy="raise",
                )

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with (
                async_sessionmaker(bind=engine)() as session
            ):
                p = ParentModel(id=1, name="Bob")
                session.add(p)
                await session.commit()

            class ParentSchema(BaseModel):
                id: int
                name: str
                label: str
                model_config = ConfigDict(
                    from_attributes=True
                )

            class ParentCreate(BaseModel):
                name: str

            router = CRUDRouter(
                schema=ParentSchema,
                create_schema=ParentCreate,
                db_model=ParentModel,
                db=get_session,
                prefix="parents",
            )
            app.include_router(router)
            return app, ParentSchema, router

        result = loop.run_until_complete(_build())
        yield result
        loop.close()

    def test_collection_not_in_orm_rels(self, collection_app):
        """uselist=True relationships are excluded from
        safety-net eager loading."""
        _app, schema, router = collection_app
        (
            _base,
            _joins,
            _jlf,
            _cffs,
            orm_rels,
            has_props,
        ) = router.get_fields(schema)
        # 'children' is uselist=True -> excluded
        assert "children" not in orm_rels
        # @property detected even without qualifying relationships
        assert has_props is True

    def test_property_works_without_collection(
        self, collection_app
    ):
        """@property that doesn't access relationships still
        works in ORM mode."""
        app, _schema, _router = collection_app
        client = TestClient(app)
        resp = client.get("/parents")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["label"] == "Parent: Bob"
