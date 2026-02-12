# pylint: disable=import-outside-toplevel,protected-access
# ruff: noqa: PLC0415
"""Tests for optional primary key type handling."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel
import pytest

from fastapi_crudrouter.schema_factory import get_pk_type


class TestGetPkTypeWithOptional:
    """Test get_pk_type correctly unwraps Optional/Union types."""

    def test_non_optional_int(self):
        """Test that non-optional int PK returns int."""

        class Schema(BaseModel):
            id: int
            name: str

        assert get_pk_type(Schema, "id") is int

    def test_optional_int_with_union(self):
        """Test that int | None PK returns int (not the union)."""

        class Schema(BaseModel):
            id: int | None = None
            name: str

        result = get_pk_type(Schema, "id")
        assert result is int, f"Expected int, got {result}"

    def test_optional_int_with_optional(self):
        """Test that Optional[int] PK returns int."""

        class Schema(BaseModel):
            id: Optional[int] = None
            name: str

        result = get_pk_type(Schema, "id")
        assert result is int, f"Expected int, got {result}"

    def test_optional_uuid(self):
        """Test that UUID | None PK returns UUID."""

        class Schema(BaseModel):
            id: UUID | None = None
            name: str

        result = get_pk_type(Schema, "id")
        assert result is UUID, f"Expected UUID, got {result}"

    def test_optional_str(self):
        """Test that str | None PK returns str."""

        class Schema(BaseModel):
            id: str | None = None
            name: str

        result = get_pk_type(Schema, "id")
        assert result is str, f"Expected str, got {result}"

    def test_missing_field_returns_int(self):
        """Test that missing PK field returns int as default."""

        class Schema(BaseModel):
            name: str

        result = get_pk_type(Schema, "id")
        assert result is int


class TestPathConverterWithOptionalPK:
    """Test that path converters work correctly with optional PK types."""

    def test_optional_int_pk_generates_int_converter(self):
        """Test that optional int PK generates :int path converter."""
        from sqlalchemy import Column, Integer, String
        from sqlalchemy.orm import declarative_base

        from fastapi_crudrouter import CRUDRouter

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "test"
            id = Column(Integer, primary_key=True)
            name = Column(String)

        class TestSchema(BaseModel):
            id: int | None = None  # Optional for auto-increment
            name: str

        async def get_db():
            pass

        router = CRUDRouter(
            schema=TestSchema,
            db_model=TestModel,
            db=get_db,
            create_route=False,
            update_route=False,
            delete_one_route=False,
            delete_all_route=False,
            get_all_route=False,
            get_one_route=False,
        )

        # Check that _get_path_converter returns "int" for optional int PK
        converter = router._get_path_converter()
        assert converter == "int", f"Expected 'int' converter, got '{converter}'"

    def test_optional_uuid_pk_generates_uuid_converter(self):
        """Test that optional UUID PK generates :uuid path converter."""
        from sqlalchemy import Column, String
        from sqlalchemy.dialects.postgresql import UUID as PGUUID
        from sqlalchemy.orm import declarative_base

        from fastapi_crudrouter import CRUDRouter

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "test"
            id = Column(PGUUID(as_uuid=True), primary_key=True)
            name = Column(String)

        class TestSchema(BaseModel):
            id: UUID | None = None
            name: str

        async def get_db():
            pass

        router = CRUDRouter(
            schema=TestSchema,
            db_model=TestModel,
            db=get_db,
            create_route=False,
            update_route=False,
            delete_one_route=False,
            delete_all_route=False,
            get_all_route=False,
            get_one_route=False,
        )

        converter = router._get_path_converter()
        assert converter == "uuid", f"Expected 'uuid' converter, got '{converter}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
