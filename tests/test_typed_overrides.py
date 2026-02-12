"""Tests for typed route overrides (e.g., @router.get('/{item_id:int}'))."""

from pydantic import BaseModel
import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

from fastapi_crudrouter import CRUDRouter

Base = declarative_base()


class SampleModel(Base):
    __tablename__ = "test"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class SampleSchema(BaseModel):
    id: int
    name: str


class TestTypedOverrides:
    """Test that both typed and untyped overrides work correctly."""

    def test_untyped_override_removes_typed_route(self):
        """Test that untyped override (/{item_id}) removes typed route (/{item_id:int})."""

        async def get_db():
            pass

        router = CRUDRouter(
            schema=SampleSchema,
            db_model=SampleModel,
            db=get_db,
            prefix="/items",
            create_route=False,
            update_route=False,
            delete_one_route=False,
            delete_all_route=False,
            get_all_route=False,
        )

        # Count GET routes with item_id path before override
        get_routes_before = [
            r
            for r in router.routes
            if "GET" in r.methods  # type: ignore
            and "{item_id" in r.path  # type: ignore
        ]
        assert len(get_routes_before) == 1, (
            f"Expected 1 route, got {len(get_routes_before)}"
        )

        # Add untyped override
        @router.get("/{item_id}")
        def custom_get():
            return {"overridden": True}

        # Count GET routes with item_id path after override
        get_routes_after = [
            r
            for r in router.routes
            if "GET" in r.methods  # type: ignore
            and "{item_id" in r.path  # type: ignore
        ]
        assert len(get_routes_after) == 1, (
            f"Expected 1 route after override, got {len(get_routes_after)}. "
            f"Routes: {[r.path for r in get_routes_after]}"
        )

        # Verify it's the custom route
        assert get_routes_after[0].endpoint is custom_get  # type: ignore

    def test_typed_override_removes_typed_route(self):
        """Test that typed override (/{item_id:int}) removes typed route (/{item_id:int})."""

        async def get_db():
            pass

        router = CRUDRouter(
            schema=SampleSchema,
            db_model=SampleModel,
            db=get_db,
            prefix="/items",
            create_route=False,
            update_route=False,
            delete_one_route=False,
            delete_all_route=False,
            get_all_route=False,
        )

        # Count GET routes with item_id path before override
        get_routes_before = [
            r
            for r in router.routes
            if "GET" in r.methods  # type: ignore
            and "{item_id" in r.path  # type: ignore
        ]
        assert len(get_routes_before) == 1

        # Add typed override (same type as original route)
        @router.get("/{item_id:int}")
        def custom_get_typed():
            return {"overridden": True, "typed": True}

        # Count GET routes with item_id path after override
        get_routes_after = [
            r
            for r in router.routes
            if "GET" in r.methods  # type: ignore
            and "{item_id" in r.path  # type: ignore
        ]
        assert len(get_routes_after) == 1, (
            f"Expected 1 route after typed override, got {len(get_routes_after)}. "
            f"Routes: {[r.path for r in get_routes_after]}"
        )

        # Verify it's the custom route
        assert get_routes_after[0].endpoint is custom_get_typed  # type: ignore

    def test_both_override_styles_work(self):
        """Test that both typed and untyped overrides can be used interchangeably."""

        async def get_db():
            pass

        # Test with untyped override
        router1 = CRUDRouter(
            schema=SampleSchema,
            db_model=SampleModel,
            db=get_db,
            prefix="/items",
            create_route=False,
            update_route=False,
            delete_all_route=False,
            get_all_route=False,
        )

        @router1.get("/{item_id}")
        def untyped_override():
            return {"style": "untyped"}

        untyped_routes = [
            r
            for r in router1.routes
            if "GET" in r.methods and "{item_id" in r.path  # type: ignore
        ]
        assert len(untyped_routes) == 1
        assert untyped_routes[0].endpoint is untyped_override  # type: ignore

        # Test with typed override
        router2 = CRUDRouter(
            schema=SampleSchema,
            db_model=SampleModel,
            db=get_db,
            prefix="/items",
            create_route=False,
            update_route=False,
            delete_all_route=False,
            get_all_route=False,
        )

        @router2.get("/{item_id:int}")
        def typed_override():
            return {"style": "typed"}

        typed_routes = [
            r
            for r in router2.routes
            if "GET" in r.methods and "{item_id" in r.path  # type: ignore
        ]
        assert len(typed_routes) == 1
        assert typed_routes[0].endpoint is typed_override  # type: ignore


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
