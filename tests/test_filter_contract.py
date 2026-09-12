"""The filter contract a client reads from OPTIONS.

A client cannot infer the accepted filters from the model schema. Guessing is
how a filter silently stops working: FastAPI drops a query parameter nobody
declared, so the list keeps answering with every row and nothing says a word.

Two ways the guess goes wrong on one schema:

* a ``Decimal`` serializes as ``"type": "string"``, so a client reads the
  column as text and asks for ``__like``, which no numeric field accepts;
* a joined column appears in the schema although no filter exists for it.

``OPTIONS`` therefore publishes what the route really accepts, under the
``x-filters`` extension key, and these tests pin that contract.
"""

import asyncio
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
import pytest
from sqlalchemy import JSON, Column, ForeignKey, Integer, Numeric, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import StaticPool

from fastapi_crudrouter import SQLAlchemyCRUDRouter

Base = declarative_base()


class Lab(Base):
    __tablename__ = "contract_lab"

    id = Column(Integer, primary_key=True)
    name = Column(String)


class Rate(Base):
    __tablename__ = "contract_rate"

    id = Column(Integer, primary_key=True)
    lab_id = Column(Integer, ForeignKey("contract_lab.id"))
    code = Column(String)
    # The column at the heart of the bug: NUMERIC maps to Decimal.
    rate = Column(Numeric(10, 4))
    # A column carrying a Pydantic constraint, which used to be mistaken for a
    # join and left with no filter at all.
    label = Column(String)
    # A column no query parameter can carry.
    tags = Column(JSON)


class RateRead(BaseModel):
    id: int
    lab_id: int
    code: Optional[str] = None
    rate: Decimal
    label: Optional[str] = Field(None, max_length=10)
    # A list column: FastAPI would make it a body field of the GET route.
    tags: Optional[list[str]] = None
    # A joined column: present in the schema, never filterable.
    lab_name: Annotated[Optional[str], Lab.name] = None


class RateCreate(BaseModel):
    lab_id: int
    code: Optional[str] = None
    rate: Decimal
    label: Optional[str] = None


async def _build_app():
    """A router over the columns above, on a database the pool really shares.

    In-memory SQLite alone gives every pooled connection its own empty
    database, so the tables would vanish between the setup and the request;
    ``StaticPool`` keeps the single connection that holds them.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)

    # The rows below reference this lab, and the read schema joins on it.
    async with session_maker() as session:
        session.add(Lab(id=1, name="VIATRIS"))
        await session.commit()

    async def get_db():
        async with session_maker() as session:
            yield session

    app = FastAPI()
    app.include_router(
        SQLAlchemyCRUDRouter(
            schema=RateRead,
            create_schema=RateCreate,
            db_model=Rate,
            db=get_db,
            prefix="rate",
        )
    )
    return app


@pytest.fixture(name="options")
def options_fixture():
    """The OPTIONS payload of a router covering every interesting column."""
    app = asyncio.run(_build_app())
    response = TestClient(app).options("/rate")
    assert response.status_code == 200
    return response.json()


class TestFilterContract:
    """What ``x-filters`` says, per column."""

    def test_options_still_returns_the_model_schema(self, options):
        """The extension is added beside the schema, it does not replace it."""
        assert options["properties"].keys() >= {"id", "code", "rate", "lab_name"}

    def test_decimal_column_advertises_a_range(self, options):
        """The regression: a rate could only be matched exactly."""
        assert options["x-filters"]["rate"] == {
            "eq": "rate",
            "gte": "rate__gte",
            "lte": "rate__lte",
            "in": "rate__in",
        }

    def test_string_column_advertises_like(self, options):
        assert options["x-filters"]["code"] == {
            "eq": "code",
            "like": "code__like",
        }

    def test_constrained_column_is_filterable(self, options):
        """A Pydantic constraint is not a join: the column keeps its filters."""
        assert options["x-filters"]["label"] == {
            "eq": "label",
            "like": "label__like",
        }

    def test_joined_column_advertises_nothing(self, options):
        """It is in the schema, so a client would have invented a filter for it."""
        assert "lab_name" not in options["x-filters"]

    def test_list_column_advertises_nothing(self, options):
        """A list cannot travel as a query parameter, so it is not a filter."""
        assert "tags" in options["properties"]
        assert "tags" not in options["x-filters"]

    def test_keys_are_whole_query_parameters(self, options):
        """The caller never builds a parameter name of its own.

        Every advertised value is sent as-is, so a client cannot append the
        wrong suffix -- which is the mistake the whole contract prevents.
        """
        for column, operators in options["x-filters"].items():
            for operator, key in operators.items():
                assert key == column if operator == "eq" else key.startswith(column)


class TestTheListRouteTakesNoBody:
    """A filter FastAPI cannot put in the query string ends up in a body.

    That body sits on a ``GET`` route: the generated client cannot fill it, and
    the route documents a payload it never reads.
    """

    def test_get_all_declares_no_request_body(self):
        app = asyncio.run(_build_app())
        operation = app.openapi()["paths"]["/rate"]["get"]
        assert "requestBody" not in operation

    def test_the_list_answers_without_one(self):
        client = TestClient(asyncio.run(_build_app()))
        assert client.get("/rate").status_code == 200


class TestAdvertisedFiltersReallyWork:
    """Every advertised key must filter, not be dropped in silence."""

    @pytest.fixture(name="client")
    def client_fixture(self):
        app = asyncio.run(_build_app())
        client = TestClient(app)
        for rate in ("2.5", "22", "40"):
            created = client.post(
                "/rate",
                json={"lab_id": 1, "code": f"c{rate}", "rate": rate, "label": "x"},
            )
            assert created.status_code == 201
        return client

    @staticmethod
    def _rates(client, params):
        response = client.get("/rate", params=params)
        assert response.status_code == 200
        payload = response.json()
        rows = payload["data"] if isinstance(payload, dict) else payload
        return sorted(Decimal(str(row["rate"])) for row in rows)

    def test_every_advertised_key_narrows_the_list(self, client):
        """The contract is only worth what its keys do.

        Sending all three rates through each advertised operator must return
        fewer rows than the unfiltered list -- an ignored parameter would
        return all of them, which is exactly the failure being guarded.
        """
        assert len(self._rates(client, {})) == 3

        assert self._rates(client, {"rate": "22"}) == [Decimal("22")]
        assert self._rates(client, {"rate__gte": "22"}) == [
            Decimal("22"),
            Decimal("40"),
        ]
        assert self._rates(client, {"rate__lte": "22"}) == [
            Decimal("2.5"),
            Decimal("22"),
        ]
        assert self._rates(client, {"rate__in": "2.5,40"}) == [
            Decimal("2.5"),
            Decimal("40"),
        ]

    def test_range_bounds_combine(self, client):
        assert self._rates(client, {"rate__gte": "2.5", "rate__lte": "22"}) == [
            Decimal("2.5"),
            Decimal("22"),
        ]

    def test_constrained_column_filters(self, client):
        """The column a Pydantic constraint used to silence."""
        assert len(self._rates(client, {"label": "x"})) == 3
        assert not self._rates(client, {"label": "nope"})
