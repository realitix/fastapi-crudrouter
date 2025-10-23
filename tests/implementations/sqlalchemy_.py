from fastapi import FastAPI
from sqlalchemy import Column, Float, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy_utils import create_database, database_exists, drop_database

from fastapi_crudrouter import CRUDRouter
from tests import (
    CUSTOM_TAGS,
    PAGINATION_SIZE,
    Carrot,
    CarrotCreate,
    CarrotUpdate,
    CustomPotato,
    Potato,
    PotatoType,
)

DSN_LIST = [
    "sqlite+aiosqlite:///./test_async.db",
    # config.POSTGRES_ASYNC_URI,  # Uncomment if you have async PostgreSQL setup
]


async def _setup_base_app(db_uri: str = DSN_LIST[0]):
    # Convert async URI to sync for database creation
    sync_uri = db_uri.replace("+aiosqlite", "").replace("sqlite:///", "sqlite:///")

    if database_exists(sync_uri):
        drop_database(sync_uri)
    create_database(sync_uri)

    app = FastAPI()

    engine = create_async_engine(db_uri)
    AsyncSessionLocal = async_sessionmaker(  # pylint: disable=invalid-name
        autocommit=False, autoflush=False, bind=engine
    )
    Base = declarative_base()  # pylint: disable=invalid-name

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


async def sqlalchemy_async_implementation(db_uri: str):
    app, engine, Base, get_session = await _setup_base_app(db_uri)  # pylint: disable=invalid-name

    class PotatoModel(Base):
        __tablename__ = "potatoes"
        id = Column(Integer, primary_key=True, index=True)
        thickness = Column(Float)
        mass = Column(Float)
        color = Column(String)
        type = Column(String)

    class CarrotModel(Base):
        __tablename__ = "carrots"
        id = Column(Integer, primary_key=True, index=True)
        length = Column(Float)
        color = Column(String)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    router_settings = [
        {
            "schema": Potato,
            "db_model": PotatoModel,
            "db": get_session,
            "prefix": "potato",
            "paginate": PAGINATION_SIZE,
        },
        {
            "schema": Carrot,
            "db_model": CarrotModel,
            "db": get_session,
            "create_schema": CarrotCreate,
            "update_schema": CarrotUpdate,
            "prefix": "carrot",
            "tags": CUSTOM_TAGS,
        },
    ]

    return app, CRUDRouter, router_settings


async def sqlalchemy_async_implementation_custom_ids():
    app, engine, Base, get_session = await _setup_base_app()  # pylint: disable=invalid-name

    class PotatoModel(Base):
        __tablename__ = "potatoes"
        potato_id = Column(Integer, primary_key=True, index=True)
        thickness = Column(Float)
        mass = Column(Float)
        color = Column(String)
        type = Column(String)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.include_router(
        CRUDRouter(schema=CustomPotato, db_model=PotatoModel, db=get_session)
    )

    return app


async def sqlalchemy_async_implementation_string_pk():
    app, engine, Base, get_session = await _setup_base_app()  # pylint: disable=invalid-name

    class PotatoTypeModel(Base):
        __tablename__ = "potato_type"
        name = Column(String, primary_key=True, index=True)
        origin = Column(String)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.include_router(
        CRUDRouter(
            schema=PotatoType,
            create_schema=PotatoType,
            db_model=PotatoTypeModel,
            db=get_session,
            prefix="potato_type",
        )
    )

    return app


async def sqlalchemy_async_implementation_integrity_errors():
    app, engine, Base, get_session = await _setup_base_app()  # pylint: disable=invalid-name

    class PotatoModel(Base):
        __tablename__ = "potatoes"
        id = Column(Integer, primary_key=True, index=True)
        thickness = Column(Float)
        mass = Column(Float)
        color = Column(String, unique=True)
        type = Column(String)

    class CarrotModel(Base):
        __tablename__ = "carrots"
        id = Column(Integer, primary_key=True, index=True)
        length = Column(Float)
        color = Column(String)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.include_router(
        CRUDRouter(
            schema=Potato,
            db_model=PotatoModel,
            db=get_session,
            create_schema=Potato,
            prefix="potatoes",
        )
    )
    app.include_router(
        CRUDRouter(
            schema=Carrot,
            db_model=CarrotModel,
            db=get_session,
            update_schema=CarrotUpdate,
            prefix="carrots",
        )
    )

    return app


# Sync wrapper functions for backward compatibility
def sqlalchemy_implementation(db_uri: str):
    import asyncio  # noqa: PLC0415 pylint: disable=import-outside-toplevel

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(sqlalchemy_async_implementation(db_uri))


def sqlalchemy_implementation_custom_ids():
    import asyncio  # noqa: PLC0415 pylint: disable=import-outside-toplevel

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(sqlalchemy_async_implementation_custom_ids())


def sqlalchemy_implementation_string_pk():
    import asyncio  # noqa: PLC0415 pylint: disable=import-outside-toplevel

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(sqlalchemy_async_implementation_string_pk())


def sqlalchemy_implementation_integrity_errors():
    import asyncio  # noqa: PLC0415 pylint: disable=import-outside-toplevel

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(sqlalchemy_async_implementation_integrity_errors())
