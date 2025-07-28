from typing import List

from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from fastapi_crudrouter import SQLAlchemyCRUDRouter
from tests import ORMModel, test_router
from tests.implementations.sqlalchemy_ import _setup_base_app

CHILD_URL = "/child"
PARENT_URL = "/parent"


class ChildSchema(ORMModel):
    parent_id: int


class ParentSchema(ORMModel):
    children: List[ChildSchema] = []


class ParentCreate(BaseModel):
    pass


async def create_app():
    app, engine, Base, session = await _setup_base_app()

    class Child(Base):
        __tablename__ = "child"
        id = Column(Integer, primary_key=True, index=True)
        parent_id = Column(Integer, ForeignKey("parent.id"))

    class Parent(Base):
        __tablename__ = "parent"
        id = Column(Integer, primary_key=True, index=True)

        children = relationship(Child, backref="parent", lazy="joined")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    parent_router = SQLAlchemyCRUDRouter(
        schema=ParentSchema,
        create_schema=ParentCreate,
        db_model=Parent,
        db=session,
        prefix=PARENT_URL,
    )
    child_router = SQLAlchemyCRUDRouter(
        schema=ChildSchema, db_model=Child, db=session, prefix=CHILD_URL
    )
    app.include_router(parent_router)
    app.include_router(child_router)

    return app


async def test_nested_models():
    app = await create_app()
    client = TestClient(app)

    parent = test_router.test_post(client, PARENT_URL, {})
    test_router.test_post(client, CHILD_URL, dict(id=0, parent_id=parent["id"]))

    res = client.get(f"{PARENT_URL}/{parent['id']}")
    assert res.status_code == 200, res.json()

    data = res.json()
    assert type(data["children"]) is list and data["children"], data
