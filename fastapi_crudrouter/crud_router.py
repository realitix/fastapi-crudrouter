# pylint: disable=too-many-lines
"""FastAPI CRUD Router - Automatic CRUD route generation.

This module provides the CRUDRouter class that automatically generates
RESTful CRUD routes for SQLAlchemy async models with Pydantic schemas.

Features:
    - Automatic CRUD route generation (GET, POST, PUT, PATCH, DELETE)
    - Advanced pagination with metadata
    - Complex filtering with operators (__like, __gte, __lte, __in)
    - Join support for relationships
    - Custom query functions
    - Permission and access control
    - Dynamic schema generation
    - Validation hooks

Basic Usage:
    >>> from fastapi import FastAPI
    >>> from fastapi_crudrouter import CRUDRouter
    >>> from sqlalchemy.ext.asyncio import AsyncSession
    >>>
    >>> app = FastAPI()
    >>>
    >>> router = CRUDRouter(
    ...     schema=UserSchema,
    ...     db_model=UserModel,
    ...     db=get_session,
    ...     prefix="/users"
    ... )
    >>> app.include_router(router)

Advanced Usage:
    >>> router = CRUDRouter(
    ...     schema=UserSchema,
    ...     db_model=UserModel,
    ...     db=get_session,
    ...     create_schema=UserCreateSchema,
    ...     update_schema=UserUpdateSchema,
    ...     filter_schema=UserFilterSchema,
    ...     paginate=100,
    ...     permission_checker=check_permission,
    ...     access_checker=check_access,
    ... )

Generated Routes:
    - GET    /resource           -> Get all (with pagination)
    - GET    /resource/{id}      -> Get one by ID
    - POST   /resource           -> Create one
    - PUT    /resource/{id}      -> Full update
    - PATCH  /resource/{id}      -> Partial update
    - DELETE /resource/{id}      -> Delete one
    - DELETE /resource           -> Delete all

See Also:
    - CRUDRouter: Main router class
    - schema_factory: Create/update schema generation
    - optional_schema_factory: PATCH schema generation
"""

from datetime import datetime, timezone
from types import UnionType
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Coroutine,
    List,
    NoReturn,
    Optional,
    Type,
    TypeAlias,
    TypedDict,
    Union,
    get_args,
    get_origin,
)
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.types import DecoratedCallable
from pydantic import BaseModel, create_model

from .config import CRUDConfig, default_config
from .filtering import FilterBuilder, OrderByBuilder
from .logging import CRUDLogger
from .pagination import PaginationResult as PaginationResultBuilder
from .pagination import PaginationValidator
from .permissions import AccessChecker, PermissionChecker
from .query_builder import QueryBuilder
from .schema_factory import (
    create_filter,
    get_pk_type,
    is_optional_type,
    optional_schema_factory,
    schema_factory,
)

try:
    from sqlalchemy import delete, func
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import IntegrityError, NoResultFound
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.ext.declarative import DeclarativeMeta
    from sqlalchemy.future import select
    from sqlalchemy.orm import DeclarativeBase
except ImportError as e:
    raise ImportError("SQLAlchemy must be installed to use fastapi-crudrouter") from e

# Type for SQLAlchemy model classes
# Using Type[DeclarativeBase] to accept any class that inherits from DeclarativeBase
ModelType = Union[Type[DeclarativeBase], DeclarativeMeta]
Model = Union[DeclarativeBase, Any]  # Model instances
SessionGenerator: TypeAlias = Callable[..., AsyncGenerator[AsyncSession, None]]

DEPENDENCIES = Optional[List[Any]]
PAGINATION = dict[str, Any]
PYDANTIC_SCHEMA = BaseModel  # pylint: disable=invalid-name

NOT_FOUND = HTTPException(404, "Item not found")


def pagination_factory(max_limit: Optional[int] = None):
    """Create a FastAPI pagination dependency.

    Creates a dependency function that validates and processes pagination
    parameters (page, skip, limit, order_by) from query strings.

    Args:
        max_limit: Maximum allowed limit value. If None, no maximum is enforced.

    Returns:
        A FastAPI Depends() function that returns a PAGINATION dict

    Raises:
        HTTPException: 422 if pagination parameters are invalid

    Examples:
        >>> paginate = pagination_factory(max_limit=100)
        >>> # In route: pagination: dict = paginate
    """

    def paginate(
        page: int = 1,
        skip: int = 0,
        limit: Optional[int] = max_limit,
        order_by: Optional[str] = None,
    ) -> PAGINATION:
        # Validate page parameter
        if page < 1:
            raise HTTPException(422, "page must be >= 1")

        # Validate skip parameter
        if skip < 0:
            raise HTTPException(422, "skip must be >= 0")

        # Validate limit parameter
        if limit is not None and (limit <= 0 or (max_limit and limit > max_limit)):
            raise HTTPException(
                422, f"limit must be > 0 and <= {max_limit if max_limit else 'max'}"
            )

        if limit and max_limit:
            limit = min(limit, max_limit)
        # If skip is provided, convert to page-based pagination
        if skip > 0 and limit:
            page = (skip // limit) + 1
        return {"page": page, "limit": limit, "skip": skip, "order_by": order_by}

    return Depends(paginate)


def find_join_condition(from_cls, target_attr):
    """Find join condition between two SQLAlchemy tables.

    Automatically discovers foreign key relationships between tables to
    construct proper JOIN conditions.

    Args:
        from_cls: Source SQLAlchemy model class
        target_attr: Target relationship attribute

    Returns:
        SQLAlchemy comparison expression for JOIN condition, or None if not found

    Examples:
        >>> # With models:
        >>> # class User(Base):
        >>> #     id = Column(Integer, primary_key=True)
        >>> # class Post(Base):
        >>> #     user_id = Column(Integer, ForeignKey('user.id'))
        >>> #     user = relationship(User)
        >>> find_join_condition(Post, Post.user)
        Post.user_id == User.id
    """
    target_cls = target_attr.class_

    from_mapper = sa_inspect(from_cls)
    target_mapper = sa_inspect(target_cls)
    target_table_name = target_mapper.local_table.name

    for fk_col in from_mapper.columns:
        for fk in fk_col.foreign_keys:
            referred_col = fk.column
            if referred_col.table.name == target_table_name:
                return fk_col == referred_col
    return None


class PaginationResult(TypedDict):
    """Pagination metadata for get_all responses.

    Attributes:
        total_records: Total number of records matching the query
        total_pages: Total number of pages with current limit
        current_page: Current page number (1-indexed)
    """

    total_records: int
    total_pages: int
    current_page: int


class GetAllResult(TypedDict):
    """Response structure for get_all endpoint.

    Attributes:
        pagination: Pagination metadata
        data: List of model instances matching the query
    """

    pagination: PaginationResult
    data: list[Model]


class CRUDRouter(APIRouter):  # pylint: disable=too-many-instance-attributes
    """FastAPI router that automatically generates CRUD routes for SQLAlchemy models.

    This router creates RESTful endpoints for Create, Read, Update, and Delete
    operations on SQLAlchemy async models with Pydantic validation.

    Attributes:
        schema: Pydantic schema for response serialization
        db_model: SQLAlchemy model class
        db_func: Async session generator function
        create_schema: Schema for POST requests (auto-generated if not provided)
        update_schema: Schema for PUT requests (auto-generated if not provided)
        patch_schema: Schema for PATCH requests (auto-generated if not provided)
        get_all_schema: Schema for GET all responses (defaults to schema)
        filter_schema: Schema for filtering (auto-generated from schema fields)
        paginate_limit: Maximum pagination limit
        access_checker: Function to check resource access
        permission_checker: Function to check permissions
        permissions: Dict mapping route names to permission requirements
        create_validator: Custom validator for create operations
        update_validator: Custom validator for update operations.
            Signature: async def(item_id: int, data: UpdateSchema, user: User, db: AsyncSession) -> UpdateSchema
        delete_validator: Custom validator for delete operations.
            Signature: async def(item_id: int, user: User, db: AsyncSession) -> None
            Raises HTTPException if deletion is not allowed.

    Args:
        schema: Pydantic schema for the model
        db_model: SQLAlchemy async model class
        db: Async session generator (e.g., from async_sessionmaker)
        create_schema: Optional custom schema for POST requests
        update_schema: Optional custom schema for PUT requests
        patch_schema: Optional custom schema for PATCH requests
        get_all_schema: Optional custom schema for GET all responses
        filter_schema: Optional custom schema for filtering
        prefix: URL prefix for routes (defaults to table name)
        tags: OpenAPI tags for documentation
        paginate: Maximum number of results per page
        get_all_route: Enable GET all route (True, False, or list of dependencies)
        get_all_options_route: Enable OPTIONS route for schema
        get_one_route: Enable GET one route
        create_route: Enable POST route
        update_route: Enable PUT/PATCH routes
        delete_one_route: Enable DELETE one route
        delete_all_route: Enable DELETE all route
        raise_callback: Custom callback for exception handling
        current_user_dependency: Dependency for getting current user
        contextual_filter: Dependency for contextual filtering
        access_checker: Function to check if user can access specific resource
        permission_checker: Function to check if user has permission
        permissions: Dict of permissions required per route
        create_validator: Custom validator for create operations
        update_validator: Custom validator for update operations.
            Signature: async def(item_id: int, data: UpdateSchema, user: User, db: AsyncSession) -> UpdateSchema
        **kwargs: Additional arguments passed to APIRouter

    Examples:
        Basic usage:
            >>> router = CRUDRouter(
            ...     schema=UserSchema,
            ...     db_model=User,
            ...     db=get_session
            ... )

        With custom schemas:
            >>> router = CRUDRouter(
            ...     schema=UserSchema,
            ...     db_model=User,
            ...     db=get_session,
            ...     create_schema=UserCreateSchema,
            ...     update_schema=UserUpdateSchema,
            ... )

        With permissions:
            >>> def check_permission(user, required_perm):
            ...     return required_perm in user.permissions
            >>>
            >>> router = CRUDRouter(
            ...     schema=UserSchema,
            ...     db_model=User,
            ...     db=get_session,
            ...     permission_checker=check_permission,
            ...     permissions={
            ...         "get_all": "users:read",
            ...         "create": "users:write",
            ...     }
            ... )

        Disable certain routes:
            >>> router = CRUDRouter(
            ...     schema=UserSchema,
            ...     db_model=User,
            ...     db=get_session,
            ...     delete_all_route=False,  # Disable delete all
            ... )

    Raises:
        ValueError: If db_model doesn't have a primary key

    Notes:
        - All routes are async by default
        - Filtering supports special operators: __like, __gte, __lte, __in
        - Pagination includes metadata: total_records, total_pages, current_page
        - PUT requires all fields, PATCH allows partial updates
        - Both PUT and PATCH respect Pydantic validators
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments,super-init-not-called
        self,
        schema: Type[PYDANTIC_SCHEMA],
        db_model: ModelType,
        db: SessionGenerator,
        create_schema: Optional[Type[PYDANTIC_SCHEMA]] = None,
        update_schema: Optional[Type[PYDANTIC_SCHEMA]] = None,
        patch_schema: Optional[Type[PYDANTIC_SCHEMA]] = None,
        get_all_schema: Optional[Type[PYDANTIC_SCHEMA]] = None,
        filter_schema: Optional[Type[PYDANTIC_SCHEMA]] = None,
        prefix: Optional[str] = None,
        tags: Optional[List[str]] = None,
        paginate: Optional[int] = None,
        get_all_route: Union[bool, DEPENDENCIES] = True,
        get_all_options_route: Union[bool, DEPENDENCIES] = True,
        get_one_route: Union[bool, DEPENDENCIES] = True,
        create_route: Union[bool, DEPENDENCIES] = True,
        update_route: Union[bool, DEPENDENCIES] = True,
        delete_one_route: Union[bool, DEPENDENCIES] = True,
        delete_all_route: Union[bool, DEPENDENCIES] = True,
        raise_callback: Optional[Callable[[Exception], None]] = None,
        current_user_dependency: Optional[Callable] = None,
        contextual_filter: Optional[Callable] = None,
        access_checker: Optional[Callable] = None,
        permission_checker: Optional[Callable] = None,
        permissions: Optional[dict[str, Any]] = None,
        create_validator: Optional[Callable] = None,
        update_validator: Optional[Callable] = None,
        delete_validator: Optional[Callable] = None,
        default_order_by: Optional[str] = None,
        create_defaults: Optional[Callable] = None,
        # Soft delete configuration
        soft_delete: bool = False,
        soft_delete_field: str = "is_deleted",
        soft_delete_value: Any = True,
        soft_delete_timestamp_field: Optional[str] = None,
        soft_delete_by_field: Optional[str] = None,
        include_deleted_param: str = "include_deleted",
        # Post-action hooks
        after_create: Optional[Callable] = None,
        after_update: Optional[Callable] = None,
        after_delete: Optional[Callable] = None,
        # Bulk operations configuration
        bulk_create_route: Union[bool, DEPENDENCIES] = False,
        bulk_update_route: Union[bool, DEPENDENCIES] = False,
        bulk_delete_route: Union[bool, DEPENDENCIES] = False,
        bulk_max_items: int = 100,
        bulk_partial_success: bool = True,
        bulk_create_validator: Optional[Callable] = None,
        config: Optional[CRUDConfig] = None,
        **kwargs: Any,
    ) -> None:
        # 0. Initialize configuration
        self.config = config or default_config

        # 1. Initialize base attributes
        self._init_base_attributes(
            schema, db_model, db, raise_callback, paginate, default_order_by
        )

        # 1b. Initialize soft delete configuration
        self._init_soft_delete(
            soft_delete,
            soft_delete_field,
            soft_delete_value,
            soft_delete_timestamp_field,
            soft_delete_by_field,
            include_deleted_param,
        )

        # 2. Initialize security hooks and lifecycle hooks
        self._init_security_hooks(
            current_user_dependency,
            contextual_filter,
            access_checker,
            permission_checker,
            permissions,
            create_validator,
            update_validator,
            delete_validator,
            create_defaults,
            after_create,
            after_update,
            after_delete,
        )

        # 2b. Initialize bulk operations configuration
        self._init_bulk_operations(
            bulk_create_route,
            bulk_update_route,
            bulk_delete_route,
            bulk_max_items,
            bulk_partial_success,
            bulk_create_validator,
        )

        # 3. Configure schemas
        self._init_schemas(
            schema, create_schema, update_schema, patch_schema, get_all_schema
        )

        # 4. Configure filtering system
        self._init_filtering(filter_schema)

        # 5. Configure pagination
        self._init_pagination(paginate)

        # 6. Determine which routes to enable
        route_config = {
            "get_all": get_all_route,
            "get_all_options": get_all_options_route,
            "get_one": get_one_route,
            "create": create_route,
            "update": update_route,
            "delete_one": delete_one_route,
            "delete_all": delete_all_route,
        }
        routes_enabled = self._check_routes_enabled(route_config)

        # 7. Initialize FastAPI router
        self._init_router(db_model, prefix, tags, routes_enabled, kwargs)

        # 8. Register routes
        if routes_enabled:
            self._register_routes(route_config)

    def _init_base_attributes(  # pylint: disable=too-many-positional-arguments
        self,
        schema: Type[PYDANTIC_SCHEMA],
        db_model: ModelType,
        db: SessionGenerator,
        raise_callback: Optional[Callable],
        paginate: Optional[int],
        default_order_by: Optional[str] = None,
    ) -> None:
        """Initialize basic attributes"""
        self.schema = schema
        self.db_model = db_model
        self.db_func = db
        self.raise_callback = raise_callback
        self.paginate_limit = paginate
        self.default_order_by = default_order_by

        # Set up primary key with validation
        pk_columns = db_model.__table__.primary_key.columns.keys()  # type: ignore[union-attr]
        if not pk_columns:
            raise ValueError(
                f"Model {db_model.__name__} must have a primary key. "
                "CRUDRouter requires a primary key column."
            )
        self._pk: str = pk_columns[0]
        self._pk_type: Any = get_pk_type(schema, self._pk)

        # Performance optimization: Cache model columns to avoid repeated getattr
        # Use col.key (Python attribute name) not col.name (DB column name)
        self._model_columns_cache: dict[str, Any] = {
            col.key: getattr(db_model, col.key) for col in sa_inspect(db_model).columns
        }

        # Initialize helper classes for modular architecture
        self._filter_builder = FilterBuilder(db_model)
        self._order_builder = OrderByBuilder(db_model, self._pk, default_order_by)
        self._pagination_validator = PaginationValidator(max_limit=paginate)
        self._query_builder = QueryBuilder(db_model)
        self._logger = CRUDLogger(db_model.__name__)

    def _init_soft_delete(  # pylint: disable=too-many-positional-arguments
        self,
        soft_delete: bool,
        soft_delete_field: str,
        soft_delete_value: Any,
        soft_delete_timestamp_field: Optional[str],
        soft_delete_by_field: Optional[str],
        include_deleted_param: str,
    ) -> None:
        """Initialize soft delete configuration"""
        self.soft_delete = soft_delete
        self.soft_delete_field = soft_delete_field
        self.soft_delete_value = soft_delete_value
        self.soft_delete_timestamp_field = soft_delete_timestamp_field
        self.soft_delete_by_field = soft_delete_by_field
        self.include_deleted_param = include_deleted_param

        # Determine the "not deleted" value (inverse of soft_delete_value)
        self._soft_delete_not_value: Optional[bool] = None
        if isinstance(soft_delete_value, bool):
            self._soft_delete_not_value = not soft_delete_value

    def _init_security_hooks(  # pylint: disable=too-many-positional-arguments
        self,
        current_user_dependency: Optional[Callable],
        contextual_filter: Optional[Callable],
        access_checker: Optional[Callable],
        permission_checker: Optional[Callable],
        permissions: Optional[dict[str, Any]],
        create_validator: Optional[Callable],
        update_validator: Optional[Callable],
        delete_validator: Optional[Callable],
        create_defaults: Optional[Callable],
        after_create: Optional[Callable],
        after_update: Optional[Callable],
        after_delete: Optional[Callable],
    ) -> None:
        """Initialize security hooks, validators, and lifecycle hooks"""
        # Keep original attributes for backward compatibility
        self.access_checker = access_checker
        self.permission_checker = permission_checker
        self.permissions = permissions or {}
        self.create_validator = create_validator
        self.update_validator = update_validator
        self.delete_validator = delete_validator
        self.create_defaults = create_defaults

        # Lifecycle hooks (post-action)
        self.after_create = after_create
        self.after_update = after_update
        self.after_delete = after_delete

        # Initialize helper classes for security
        self._permission_checker = PermissionChecker(
            permission_checker=permission_checker,
            permissions=permissions,
        )
        self._access_checker = AccessChecker(access_checker=access_checker)

        # Wrap hooks in Depends() for FastAPI injection
        if current_user_dependency:
            self.current_user_depends = Depends(current_user_dependency)
        else:
            self.current_user_depends = None

        if contextual_filter:
            self.contextual_filter_depends = Depends(contextual_filter)
        else:
            self.contextual_filter_depends = Depends(lambda: {})

    def _init_bulk_operations(  # pylint: disable=too-many-positional-arguments
        self,
        bulk_create_route: Union[bool, DEPENDENCIES],
        bulk_update_route: Union[bool, DEPENDENCIES],
        bulk_delete_route: Union[bool, DEPENDENCIES],
        bulk_max_items: int,
        bulk_partial_success: bool,
        bulk_create_validator: Optional[Callable],
    ) -> None:
        """Initialize bulk operations configuration"""
        self.bulk_create_route = bulk_create_route
        self.bulk_update_route = bulk_update_route
        self.bulk_delete_route = bulk_delete_route
        self.bulk_max_items = bulk_max_items
        self.bulk_partial_success = bulk_partial_success
        self.bulk_create_validator = bulk_create_validator

    def _init_schemas(  # pylint: disable=too-many-positional-arguments
        self,
        schema: Type[PYDANTIC_SCHEMA],
        create_schema: Optional[Type[PYDANTIC_SCHEMA]],
        update_schema: Optional[Type[PYDANTIC_SCHEMA]],
        patch_schema: Optional[Type[PYDANTIC_SCHEMA]],
        get_all_schema: Optional[Type[PYDANTIC_SCHEMA]],
    ) -> None:
        """Initialize CRUD schemas"""
        self.create_schema = (
            create_schema
            if create_schema
            else schema_factory(schema, pk_field_name=self._pk, name="Create")
        )
        self.update_schema = (
            update_schema
            if update_schema
            else schema_factory(schema, pk_field_name=self._pk, name="Update")
        )
        self.patch_schema = (
            patch_schema
            if patch_schema
            else optional_schema_factory(
                self.update_schema, pk_field_name=self._pk, name="Patch"
            )
        )
        self.get_all_schema = get_all_schema if get_all_schema else schema

        # Extract computed column names from get_all_schema for sorting support
        _, _, _, custom_func_fields = self.get_fields(self.get_all_schema)
        self._order_builder.set_computed_columns(set(custom_func_fields.keys()))

    def _init_filtering(self, filter_schema: Optional[Type[PYDANTIC_SCHEMA]]) -> None:
        """Initialize filtering system"""
        # Generate automatic filter fields from schema
        auto_filter_fields = self._generate_auto_filter_fields()

        # Merge with custom filter_schema if provided
        if filter_schema:
            # Add only auto fields that are NOT in filter_schema
            # This preserves custom filter fields with their metadata (callbacks)
            additional_fields = {
                name: value
                for name, value in auto_filter_fields.items()
                if name not in filter_schema.model_fields
            }

            # Inherit from filter_schema to preserve metadata (callbacks)
            base_filter = create_model(  # type: ignore[call-overload]
                f"{self.schema.__name__}Filter",
                __base__=filter_schema,  # Preserves callbacks and metadata
                **additional_fields,
            )
            self.filter_schema = create_filter(base_filter)
        # Use only auto-generated fields
        elif auto_filter_fields:
            base_filter = create_model(  # type: ignore[call-overload]
                f"{self.schema.__name__}AutoFilter", **auto_filter_fields
            )
            self.filter_schema = create_filter(base_filter)
        else:
            self.filter_schema = None  # type: ignore[assignment]

        self.filter_depends: Any = (
            Depends(self.filter_schema) if self.filter_schema else Depends(lambda: None)
        )

    def _generate_auto_filter_fields(self) -> dict[str, tuple]:
        """Generate automatic filter fields from schema"""
        auto_filter_fields = {}

        for field_name, field_info in self.schema.model_fields.items():
            # Only include simple fields (exclude joins, custom functions)
            if not field_info.metadata:
                # Make field optional for filtering
                origin = get_origin(field_info.annotation)
                if origin is UnionType and type(None) in get_args(
                    field_info.annotation
                ):
                    # Already optional
                    auto_filter_fields[field_name] = (field_info.annotation, None)
                else:
                    # Make it optional
                    optional_type: Any = Optional[field_info.annotation]
                    auto_filter_fields[field_name] = (optional_type, None)

        return auto_filter_fields

    def _init_pagination(self, paginate: Optional[int]) -> None:
        """Initialize pagination"""
        self.pagination = pagination_factory(max_limit=paginate)

    def _check_routes_enabled(self, route_config: dict[str, Any]) -> bool:
        """Check if any routes are enabled"""

        def is_route_enabled(route):
            return route is not False and route is not None

        return any(is_route_enabled(route) for route in route_config.values())

    def _get_path_converter(self) -> str:
        """Get Starlette path converter type for primary key.

        Maps Python types to Starlette path converters to enable type-specific
        routing and prevent route conflicts with custom endpoints.

        Returns:
            str: Path converter type ("int", "uuid", "str", or "float")

        Examples:
            >>> # For Invoice model with id: int
            >>> router._get_path_converter()
            'int'
            >>> # Generates route: /{item_id:int} which only matches numbers
            >>> # Custom route /deleted won't conflict with /{item_id:int}
        """
        if self._pk_type is int:
            return "int"
        if self._pk_type is UUID:
            return "uuid"
        if self._pk_type is str:
            return "str"
        if self._pk_type is float:
            return "float"
        # Fallback to str for unknown types (most permissive)
        return "str"

    def _init_router(  # pylint: disable=too-many-positional-arguments
        self,
        db_model: ModelType,
        prefix: Optional[str],
        tags: Optional[List[str]],
        routes_enabled: bool,
        kwargs: Any,
    ) -> None:
        """Initialize FastAPI router"""
        if routes_enabled:
            table_name = db_model.__tablename__  # type: ignore[union-attr]
            prefix = str(prefix if prefix else table_name).lower()
            prefix = "/" + prefix.strip("/")
            tags_list: Any = tags or [prefix.strip("/").capitalize()]
            super().__init__(prefix=prefix, tags=tags_list, **kwargs)
        else:
            # Initialize router with empty prefix if no routes are enabled
            super().__init__(prefix="", **kwargs)

    def _register_routes(self, route_config: dict[str, Any]) -> None:
        """Register all enabled routes"""

        # Build path with type converter for item_id routes
        # Example: "/{item_id:int}" for int PKs, "/{item_id:uuid}" for UUID PKs
        # This prevents route conflicts (e.g., /deleted won't match /{item_id:int})
        path_converter = self._get_path_converter()
        item_id_path = f"/{{item_id:{path_converter}}}"

        # Create response models
        class PaginationResultModel(BaseModel):
            total_records: int
            total_pages: int
            current_page: int

        class GetAllResponseModel(BaseModel):
            pagination: PaginationResultModel
            data: list[self.get_all_schema]  # type: ignore

        # Register each route
        if route_config["get_all"]:
            self._add_api_route(
                "",
                self._get_all(),
                methods=["GET"],
                response_model=GetAllResponseModel,
                summary="Get All",
                dependencies=route_config["get_all"],
            )

        if route_config.get("get_all_options"):
            self._add_api_route(
                "",
                self._get_all_options,
                methods=["OPTIONS"],
                response_model=dict[str, Any],
                summary="Get All Schema",
                dependencies=route_config["get_all_options"],
            )

        if route_config["create"]:
            self._add_api_route(
                "",
                self._create(),
                methods=["POST"],
                response_model=self.schema,
                summary="Create One",
                status_code=201,
                dependencies=route_config["create"],
            )

        if route_config.get("delete_all"):
            self._add_api_route(
                "",
                self._delete_all(),
                methods=["DELETE"],
                response_model=GetAllResponseModel,
                summary="Delete All",
                dependencies=route_config["delete_all"],
            )

        if route_config["get_one"]:
            self._add_api_route(
                item_id_path,
                self._get_one(),
                methods=["GET"],
                response_model=self.schema,
                summary="Get One",
                dependencies=route_config["get_one"],
                error_responses=[NOT_FOUND],
            )

        if route_config["update"]:
            # PUT route - full replacement
            self._add_api_route(
                item_id_path,
                self._update(),
                methods=["PUT"],
                response_model=self.schema,
                summary="Update One",
                dependencies=route_config["update"],
                error_responses=[NOT_FOUND],
            )

            # PATCH route - partial update
            self._add_api_route(
                item_id_path,
                self._patch(),
                methods=["PATCH"],
                response_model=self.schema,
                summary="Partially Update One",
                dependencies=route_config["update"],
                error_responses=[NOT_FOUND],
            )

        if route_config["delete_one"]:
            self._add_api_route(
                item_id_path,
                self._delete_one(),
                methods=["DELETE"],
                response_model=None,
                summary="Delete One",
                status_code=204,
                dependencies=route_config["delete_one"],
                error_responses=[NOT_FOUND],
            )

        # Bulk operations routes
        if self.bulk_create_route:
            self._add_api_route(
                "/bulk",
                self._bulk_create(),
                methods=["POST"],
                response_model=dict[str, Any],
                summary="Bulk Create",
                status_code=201,
                dependencies=(
                    self.bulk_create_route
                    if isinstance(self.bulk_create_route, list)
                    else []
                ),
            )

        if self.bulk_update_route:
            self._add_api_route(
                "/bulk",
                self._bulk_update(),
                methods=["PATCH"],
                response_model=dict[str, Any],
                summary="Bulk Update",
                dependencies=(
                    self.bulk_update_route
                    if isinstance(self.bulk_update_route, list)
                    else []
                ),
            )

        if self.bulk_delete_route:
            self._add_api_route(
                "/bulk",
                self._bulk_delete(),
                methods=["DELETE"],
                response_model=dict[str, Any],
                summary="Bulk Delete",
                dependencies=(
                    self.bulk_delete_route
                    if isinstance(self.bulk_delete_route, list)
                    else []
                ),
            )

    def _add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        dependencies: Union[bool, DEPENDENCIES],
        error_responses: Optional[List[HTTPException]] = None,
        **kwargs: Any,
    ) -> None:
        dependencies = [] if isinstance(dependencies, bool) else dependencies
        responses: Any = (
            {err.status_code: {"detail": err.detail} for err in error_responses}
            if error_responses
            else None
        )

        super().add_api_route(
            path, endpoint, dependencies=dependencies, responses=responses, **kwargs
        )

    def api_route(
        self, path: str, *args: Any, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """Overrides an existing route if it exists"""
        methods = kwargs.get("methods", ["GET"])
        self.remove_api_route(path, methods)
        return super().api_route(path, *args, **kwargs)

    def get(
        self, path: str, *args: Any, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        self.remove_api_route(path, ["GET"])
        return super().get(path, *args, **kwargs)

    def post(
        self, path: str, *args: Any, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        self.remove_api_route(path, ["POST"])
        return super().post(path, *args, **kwargs)

    def put(
        self, path: str, *args: Any, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        self.remove_api_route(path, ["PUT"])
        return super().put(path, *args, **kwargs)

    def delete(
        self, path: str, *args: Any, **kwargs: Any
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        self.remove_api_route(path, ["DELETE"])
        return super().delete(path, *args, **kwargs)

    def remove_api_route(self, path: str, methods: List[str]) -> None:
        methods_ = set(methods)
        full_path = f"{self.prefix}{path}"

        for route in self.routes:
            # Match both path_format (normalized, for untyped overrides like
            # /{item_id}) and path (raw, for typed overrides like /{item_id:int})
            # This allows users to override routes with or without type converters.
            route_path_format = getattr(route, "path_format", route.path)  # type: ignore
            route_path = route.path  # type: ignore
            if (
                full_path in (route_path_format, route_path)
                and route.methods == methods_  # type: ignore
            ):
                self.routes.remove(route)

    def _get_filter_metadata(self, filter_key: str) -> Any:
        """Get metadata for filter field.

        Extracts custom metadata from filter schema fields, typically
        used for custom filter functions or join-based filtering.

        Args:
            filter_key: Name of the filter field

        Returns:
            Metadata object (usually a relationship or callable), or None

        Examples:
            >>> # In filter schema:
            >>> class UserFilter(BaseModel):
            ...     department: Optional[str] = Field(None, metadata=[Department.name])
            >>> metadata = router._get_filter_metadata("department")
            >>> # metadata = Department.name (relationship attribute)
        """
        if not self.filter_schema:
            return None
        model_fields = self.filter_schema.model_fields
        if filter_key not in model_fields:
            return None
        metadata = model_fields[filter_key].metadata
        if not metadata:
            return None
        return metadata[0]

    def _get_model_column(self, field_name: str) -> Any:
        """Get model column with caching for performance"""
        if field_name in self._model_columns_cache:
            return self._model_columns_cache[field_name]
        # Fallback to getattr if not in cache
        return getattr(self.db_model, field_name)

    def get_fields(self, schema) -> Any:
        """Parse schema fields to identify joins, list joins, and custom functions.

        Analyzes a Pydantic schema's fields to separate:
        - Base model fields (direct columns)
        - Join fields (single relationships)
        - Join list fields (one-to-many relationships)
        - Custom function fields (computed fields)

        Args:
            schema: Pydantic schema to parse

        Returns:
            Tuple of (base_class_fields, join_fields, join_list_fields, custom_func_fields)
            - base_class_fields: List of SQLAlchemy column attributes
            - join_fields: Dict of field_name -> (relationship, is_outer_join)
            - join_list_fields: Dict of field_name -> (table, foreign_key, schema)
            - custom_func_fields: Dict of field_name -> custom_function

        Examples:
            >>> class UserSchema(BaseModel):
            ...     id: int
            ...     name: str
            ...     posts: List[PostSchema] = Field(metadata=[...])
            >>> base, joins, list_joins, funcs = router.get_fields(UserSchema)
            >>> # base = [User.id, User.name]
            >>> # list_joins = {'posts': (Post, Post.user_id, PostSchema)}
        """

        def type_can_be_none(type_hint):
            if get_origin(type_hint) is UnionType:
                return type(None) in get_args(type_hint)
            return False

        def remove_operator_fields(fields):
            return {k: v for k, v in fields.items() if "__" not in k}

        base_class_fields = []
        join_fields = {}
        join_list_fields = {}
        custom_func_fields = {}

        # Pydantic v2 only
        fields_dict = schema.model_fields

        for field, annotation in remove_operator_fields(fields_dict).items():
            if not hasattr(annotation, "metadata") or not annotation.metadata:
                if hasattr(self.db_model, field):
                    # Only include actual SQLAlchemy columns, not Python properties
                    attr = getattr(self.db_model, field)
                    # Check if it's an InstrumentedAttribute (SQLAlchemy column)
                    if hasattr(attr, "property") and hasattr(attr.property, "columns"):
                        base_class_fields.append(attr)
            else:
                attribute = annotation.metadata[0]
                # Pydantic v2 only
                field_annotation = annotation.annotation
                # Check callable first: custom_func_fields take priority
                # regardless of field type (including list fields)
                if callable(attribute) and not isinstance(attribute, (list, tuple)):
                    custom_func_fields[field] = attribute
                elif get_origin(field_annotation) is list:
                    list_args = get_args(field_annotation)
                    read_cls = list_args[0]
                    foreign_key = attribute[1]
                    join_list_fields[field] = (attribute[0], foreign_key, read_cls)
                elif hasattr(attribute, "class_"):
                    # Only treat as join field if it's a SQLAlchemy relationship (has .class_ attribute)
                    join_fields[field] = (attribute, type_can_be_none(field_annotation))
                # Metadata exists but is not a relationship, callable, or list
                # Check if it's still a real DB column (e.g., field with Pydantic constraints)
                elif hasattr(self.db_model, field):
                    attr = getattr(self.db_model, field)
                    if hasattr(attr, "property") and hasattr(attr.property, "columns"):
                        base_class_fields.append(attr)
                    # Otherwise ignore (Pydantic constraint on computed field)

        return base_class_fields, join_fields, join_list_fields, custom_func_fields

    def compute_query_join(self, query, join_fields) -> Any:
        """Add JOIN clauses to query for relationship fields.

        Automatically determines join conditions using foreign keys and adds
        the necessary JOIN clauses. Prevents duplicate joins.

        Args:
            query: SQLAlchemy select query
            join_fields: Dict of label -> (attribute, is_outer) from get_fields()

        Returns:
            Modified query with JOIN clauses added

        Notes:
            - Automatically finds join conditions via foreign keys
            - Uses LEFT OUTER JOIN if is_outer is True
            - Tracks already joined tables to prevent duplicates
            - Adds relationship columns with labels to select
        """
        already_joined = set()
        for label, (attribute, isouter) in join_fields.items():
            if attribute.class_ not in already_joined:
                args = [attribute.class_]
                join_condition = find_join_condition(self.db_model, attribute)
                if join_condition is not None:
                    args.append(join_condition)
                query = query.join(*args, isouter=isouter)
                already_joined.add(attribute.class_)
            query = query.add_columns(attribute.label(label))
        return query

    async def compute_subdata(
        self, db: AsyncSession, model_id: Any, join_list_fields: dict
    ) -> Any:
        """Compute subdata for one-to-many relationships.

        Fetches related records for list-type joins (one-to-many relationships)
        for a single parent record.

        Args:
            db: Active async database session
            model_id: Primary key value of the parent record
            join_list_fields: Dict from get_fields() with list join definitions

        Returns:
            Dict mapping field names to lists of related Pydantic models

        Examples:
            >>> # For a User with multiple Posts:
            >>> subdata = await router.compute_subdata(db, user_id=1, join_list_fields)
            >>> # subdata = {'posts': [PostSchema(...), PostSchema(...)]}

        Notes:
            - Executes one query per relationship field
            - Can cause N+1 query problem (see Week 2 for optimization)
        """
        subdata: dict[str, Any] = {}
        for field, (attribute, foreign_key, read_cls) in join_list_fields.items():
            subdata[field] = []
            subres = (
                await db.execute(
                    select(*attribute.__table__.columns).where(foreign_key == model_id)
                )
            ).all()
            for subrow in subres:
                subdata[field].append(read_cls(**subrow._asdict()))
        return subdata

    async def compute_subdata_batch(
        self, db: AsyncSession, model_ids: List[Any], join_list_fields: dict
    ) -> dict[Any, dict[str, Any]]:
        """Compute subdata for multiple models at once (solves N+1 query problem)

        This method batches all subdata queries to avoid N+1 query performance issues.
        Instead of executing one query per model, it executes queries in chunks to
        respect database bind parameter limits (e.g., SQLite's 999 limit).
        """
        # Initialize result dictionary with empty subdatas
        result: dict[Any, dict[str, Any]] = {mid: {} for mid in model_ids}

        if not join_list_fields or not model_ids:
            return result

        # Chunk size to avoid exceeding database bind parameter limits
        # SQLite default limit is 999, so 500 gives a safe margin
        CHUNK_SIZE = 500

        # Process each join_list field
        for field, (attribute, foreign_key, read_cls) in join_list_fields.items():
            # Group results by foreign key value
            grouped: dict[Any, list] = {mid: [] for mid in model_ids}

            # Process model_ids in chunks to avoid database limits
            for i in range(0, len(model_ids), CHUNK_SIZE):
                chunk = model_ids[i : i + CHUNK_SIZE]

                # Query for this chunk of IDs
                subres = (
                    await db.execute(
                        select(*attribute.__table__.columns).where(
                            foreign_key.in_(chunk)
                        )
                    )
                ).all()

                # Group results from this chunk
                for subrow in subres:
                    # pylint: disable=protected-access
                    row_dict = (
                        subrow._asdict()
                        if hasattr(subrow, "_asdict")
                        else dict(subrow._mapping)
                    )
                    # Get the foreign key value from the subrow
                    # Use foreign_key.key (ORM attribute) to match row_dict keys
                    fk_value = row_dict.get(foreign_key.key)
                    if fk_value in grouped:
                        grouped[fk_value].append(read_cls(**row_dict))

            # Assign grouped results to the final result
            for mid in model_ids:
                result[mid][field] = grouped[mid]

        return result

    def compute_custom_func(self, query, custom_func_fields: dict) -> Any:
        """Apply custom functions to query"""
        for _field, fun in custom_func_fields.items():
            query = fun(query)
        return query

    def _get_all_options(self) -> dict[str, Any]:
        """Get schema options"""
        return self.get_all_schema.model_json_schema(
            ref_template="{model}", mode="serialization"
        )

    def _raise(self, e: Exception, status_code: int = 422) -> NoReturn:
        """Handle exceptions with optional callback"""
        if self.raise_callback:
            self.raise_callback(e)
        raise HTTPException(status_code, ", ".join(e.args)) from e

    @staticmethod
    def get_routes() -> List[str]:
        """Get list of available routes"""
        return [
            "get_all",
            "get_all_options",
            "create",
            "delete_all",
            "get_one",
            "update",
            "delete_one",
        ]

    def _get_all(self) -> Callable[..., Coroutine[Any, Any, GetAllResult]]:
        """Get all items with pagination and filtering"""

        async def route(  # pylint: disable=too-many-positional-arguments
            db: AsyncSession = Depends(self.db_func),
            pagination: PAGINATION = self.pagination,
            filters: self.filter_schema = self.filter_depends,  # type: ignore[name-defined]
            contextual_filters: dict = self.contextual_filter_depends,
            user: Any = self.current_user_depends,
            include_deleted: bool = False,
        ) -> GetAllResult:
            # 1. Check permissions
            self._check_permission(user, "get_all")

            # 2. Parse pagination
            page, limit, skip = self._parse_pagination(pagination)

            # 3. Build base query with joins and custom functions
            query, join_list_fields = self._build_base_query(self.get_all_schema)

            # 4. Apply soft delete filter (exclude deleted items unless include_deleted=True)
            if self.soft_delete and not include_deleted:
                query = self._apply_soft_delete_filter(query)

            # 5. Apply filters
            query = self._apply_filters(query, filters, contextual_filters)

            # 6. Count total records (before ordering - ORDER BY breaks COUNT on PostgreSQL)
            count = await self._count_total(db, query)

            # 7. Apply ordering
            query = query.order_by(self._get_order_by(pagination))

            # 8. Execute query with pagination
            rows = await self._execute_paginated_query(db, query, limit, skip)

            # 9. Process results into models
            db_models = await self._process_results(
                db, rows, self.get_all_schema, join_list_fields
            )

            # 10. Build paginated response
            return self._build_paginated_response(db_models, count, page, limit)

        return route

    def _check_permission(self, user: Any, action: str) -> None:
        """Check if user has permission for action"""
        if (
            self.permission_checker
            and action in self.permissions
            and user
            and not self.permission_checker(user, self.permissions[action])
        ):
            raise HTTPException(
                403, f"No permission to {action.replace('_', ' ')} resources"
            )

    def _parse_pagination(
        self, pagination: PAGINATION
    ) -> tuple[int, Optional[int], int]:
        """Parse pagination parameters"""
        page = pagination.get("page", 1)
        limit = pagination.get("limit")
        skip = pagination.get("skip", 0)

        if skip == 0 and limit:
            skip = (page - 1) * limit

        return page, limit, skip

    def _build_base_query(self, schema: Type[PYDANTIC_SCHEMA]) -> tuple[Any, Any]:
        """Build base query with joins and custom functions"""
        (
            base_class_fields,
            join_fields,
            join_list_fields,
            custom_func_fields,
        ) = self.get_fields(schema)

        query = select(*base_class_fields)
        query = self.compute_query_join(query, join_fields)
        query = self.compute_custom_func(query, custom_func_fields)

        return query, join_list_fields

    def _apply_filters(
        self,
        query: Any,
        filters: Optional[PYDANTIC_SCHEMA],
        contextual_filters: dict,
    ) -> Any:
        """Apply filters to query using FilterBuilder"""
        return self._filter_builder.apply_filters(
            query,
            filters,
            contextual_filters=contextual_filters,
            filter_metadata_getter=self._get_filter_metadata,
        )

    def _apply_soft_delete_filter(self, query: Any) -> Any:
        """Apply soft delete filter to exclude deleted items.

        Filters out items where soft_delete_field equals soft_delete_value.
        For boolean fields with soft_delete_value=True, this filters where is_deleted=False or NULL.
        """
        if not self.soft_delete:
            return query

        soft_delete_col = getattr(self.db_model, self.soft_delete_field, None)
        if soft_delete_col is None:
            return query

        if self._soft_delete_not_value is not None:
            # Boolean field: filter for "not deleted" value
            query = query.where(
                (soft_delete_col == self._soft_delete_not_value)
                | (soft_delete_col.is_(None))
            )
        else:
            # Non-boolean field: filter where field IS NULL
            query = query.where(soft_delete_col.is_(None))

        return query

    def _get_order_by(self, pagination: PAGINATION) -> Any:
        """Get order by clause from pagination using OrderByBuilder"""
        order_by = pagination.get("order_by")
        return self._order_builder.get_order_by(order_by)

    async def _execute_paginated_query(
        self, db: AsyncSession, query: Any, limit: Optional[int], skip: int
    ) -> list:
        """Execute query with pagination"""
        result = await db.execute(query.limit(limit).offset(skip))
        return list(result.all())

    async def _count_total(self, db: AsyncSession, query: Any) -> int:
        """Count total records for query"""
        # pylint: disable=not-callable
        query_count = query.with_only_columns(func.count()).select_from(self.db_model)
        count_result = (await db.execute(query_count)).first()
        return count_result[0] if count_result else 0

    async def _process_results(
        self,
        db: AsyncSession,
        rows: list,
        schema: Type[PYDANTIC_SCHEMA],
        join_list_fields: Any,
    ) -> List[Model]:
        """Process query results into schema models"""
        db_models: List[Model] = []

        if join_list_fields:
            # Extract all primary keys first for batch loading
            model_ids = []
            rows_data = []
            for row in rows:
                # pylint: disable=protected-access
                row_dict = (
                    row._asdict() if hasattr(row, "_asdict") else dict(row._mapping)
                )
                pk_value = row_dict.get(self._pk, getattr(row, self._pk, None))
                model_ids.append(pk_value)
                rows_data.append(row_dict)

            # Batch load all subdata in one call (solves N+1 problem)
            batch_subdata = await self.compute_subdata_batch(
                db, model_ids, join_list_fields
            )

            # Build models with pre-loaded subdata
            for row_dict, pk_value in zip(rows_data, model_ids):
                subdata = batch_subdata.get(pk_value, {})
                model = schema(**row_dict, **subdata)
                db_models.append(model)
        else:
            # No joins, simpler path
            for row in rows:
                # pylint: disable=protected-access
                row_dict = (
                    row._asdict() if hasattr(row, "_asdict") else dict(row._mapping)
                )
                model = schema(**row_dict)
                db_models.append(model)

        return db_models

    def _build_paginated_response(
        self,
        data: List[Model],
        total_count: int,
        page: int,
        limit: Optional[int],
    ) -> GetAllResult:
        """Build paginated response using PaginationResult"""
        result = PaginationResultBuilder.build(data, total_count, page, limit)
        return result  # type: ignore[return-value]

    def _get_one(self) -> Callable[..., Coroutine[Any, Any, Model]]:
        """Get one item by ID"""

        async def route(
            item_id: self._pk_type,  # type: ignore[name-defined]
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> Model:
            # Permission check
            if (
                self.permission_checker
                and "get_one" in self.permissions
                and user
                and not self.permission_checker(user, self.permissions["get_one"])
            ):
                raise HTTPException(403, "No permission to view this resource")

            # Access check
            if self.access_checker and user:
                await self.access_checker(item_id, user, db)

            try:
                base_class_fields, join_fields, join_list_fields, custom_func_fields = (
                    self.get_fields(self.schema)
                )
                query = select(*base_class_fields)
                query = self.compute_query_join(query, join_fields)
                query = self.compute_custom_func(query, custom_func_fields)
                query = query.select_from(self.db_model)
                query = query.where(getattr(self.db_model, self._pk) == item_id)

                # Apply soft delete filter (exclude soft-deleted items)
                if self.soft_delete:
                    query = self._apply_soft_delete_filter(query)

                row = (await db.execute(query)).one()
                # pylint: disable=protected-access
                row_dict = (
                    row._asdict() if hasattr(row, "_asdict") else dict(row._mapping)
                )
                pk_value = row_dict.get(self._pk, getattr(row, self._pk, None))
                subdata = await self.compute_subdata(db, pk_value, join_list_fields)
                model = self.schema(**row_dict, **subdata)
            except NoResultFound:
                model = None

            if model:
                return model
            raise NOT_FOUND from None

        return route

    def _create(self) -> Callable[..., Coroutine[Any, Any, Model]]:
        """Create new item"""

        async def route(
            model: self.create_schema,  # type: ignore[name-defined]
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> Model:
            # Permission check
            if (
                self.permission_checker
                and "create" in self.permissions
                and user
                and not self.permission_checker(user, self.permissions["create"])
            ):
                raise HTTPException(403, "No permission to create resources")

            # Apply create_defaults before validation
            # Defaults are merged with incoming data (explicit values override defaults)
            if self.create_defaults and user:
                defaults = self.create_defaults(user)
                if defaults:
                    # Get explicit values from incoming model
                    model_data = model.model_dump()
                    model_fields_set = model.model_fields_set

                    # Merge: defaults first, then explicit values override
                    merged_data = {**defaults}
                    for key, value in model_data.items():
                        # Only override if the field was explicitly set in the request
                        if key in model_fields_set:
                            merged_data[key] = value
                        elif key not in merged_data:
                            # Field not in defaults and not explicitly set: use model value
                            merged_data[key] = value

                    # Reconstruct model with merged data
                    model = self.create_schema(**merged_data)

            # Business validation
            if self.create_validator and user:
                model = await self.create_validator(model, user, db)

            try:
                db_model: Model = self.db_model(**model.model_dump())
                db.add(db_model)
                await db.commit()
                await db.refresh(db_model)

                # Call after_create hook (after commit)
                if self.after_create:
                    try:
                        await self.after_create(db_model, user, db)
                    except Exception as hook_error:  # pylint: disable=broad-except
                        # Log hook errors but don't fail the main operation
                        self._logger.error(f"after_create hook error: {hook_error}")

                return await self._get_one()(
                    item_id=getattr(db_model, self._pk), db=db, user=user
                )
            except IntegrityError as e:
                await db.rollback()
                self._raise(e)

        return route

    def _update(self) -> Callable[..., Coroutine[Any, Any, Model]]:
        """Full update existing item (PUT)

        PUT (RFC 7231): Full replacement - all fields must be provided.
        Uses update_schema where fields without defaults are required.
        """

        async def route(
            item_id: self._pk_type,  # type: ignore[name-defined]
            model: self.update_schema,  # type: ignore[name-defined]
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> Model:
            # Permission check
            if (
                self.permission_checker
                and "update" in self.permissions
                and user
                and not self.permission_checker(user, self.permissions["update"])
            ):
                raise HTTPException(403, "No permission to update resources")

            # Access check
            if self.access_checker and user:
                await self.access_checker(item_id, user, db)

            # Business validation (optional)
            if self.update_validator and user:
                model = await self.update_validator(item_id, model, user, db)

            try:
                db_model: Model = await db.get(self.db_model, item_id)
                if not db_model:
                    raise NOT_FOUND from None

                # PUT: Only update fields explicitly provided by the client
                # to avoid overwriting stored values with schema defaults
                all_data = model.model_dump(exclude={self._pk})
                update_data = {
                    key: value
                    for key, value in all_data.items()
                    if key in model.model_fields_set
                }

                for key, value in update_data.items():
                    if hasattr(db_model, key):
                        setattr(db_model, key, value)

                await db.commit()
                await db.refresh(db_model)

                # Call after_update hook (after commit)
                if self.after_update:
                    try:
                        await self.after_update(db_model, user, db)
                    except Exception as hook_error:  # pylint: disable=broad-except
                        # Log hook errors but don't fail the main operation
                        self._logger.error(f"after_update hook error: {hook_error}")

                return await self._get_one()(
                    item_id=getattr(db_model, self._pk), db=db, user=user
                )
            except IntegrityError as e:
                await db.rollback()
                self._raise(e)

        return route

    def _patch(self) -> Callable[..., Coroutine[Any, Any, Model]]:
        """Partially update existing item (PATCH)

        PATCH (RFC 5789): Partial update - only provided fields are modified.
        Uses patch_schema where all fields are optional.
        """

        async def route(
            item_id: self._pk_type,  # type: ignore[name-defined]
            model: self.patch_schema,  # type: ignore[name-defined]
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> Model:
            # Permission check
            if (
                self.permission_checker
                and "update" in self.permissions
                and user
                and not self.permission_checker(user, self.permissions["update"])
            ):
                raise HTTPException(403, "No permission to update resources")

            # Access check
            if self.access_checker and user:
                await self.access_checker(item_id, user, db)

            # Business validation (optional)
            if self.update_validator and user:
                model = await self.update_validator(item_id, model, user, db)

            try:
                db_model: Model = await db.get(self.db_model, item_id)
                if not db_model:
                    raise NOT_FOUND from None

                # PATCH: Only update fields that were provided
                update_data = model.model_dump(exclude_unset=True, exclude={self._pk})

                # Validate non-nullable fields: reject explicit null
                # for non-optional fields
                for key, value in update_data.items():
                    if value is None:
                        # Check if this field was originally optional
                        # in the update schema (use update_schema, not
                        # the read schema, to respect write rules)
                        original_field = self.update_schema.model_fields.get(key)
                        if original_field and not is_optional_type(
                            original_field.annotation
                        ):
                            raise HTTPException(
                                422, detail=f"Field '{key}' cannot be null"
                            )

                for key, value in update_data.items():
                    if hasattr(db_model, key):
                        setattr(db_model, key, value)

                await db.commit()
                await db.refresh(db_model)

                # Call after_update hook (after commit)
                if self.after_update:
                    try:
                        await self.after_update(db_model, user, db)
                    except Exception as hook_error:  # pylint: disable=broad-except
                        # Log hook errors but don't fail the main operation
                        self._logger.error(f"after_update hook error: {hook_error}")

                return await self._get_one()(
                    item_id=getattr(db_model, self._pk), db=db, user=user
                )
            except IntegrityError as e:
                await db.rollback()
                self._raise(e)

        return route

    def _delete_all(self) -> Callable[..., Coroutine[Any, Any, GetAllResult]]:
        """Delete all items"""

        async def route(db: AsyncSession = Depends(self.db_func)) -> GetAllResult:
            # Use SQLAlchemy delete API instead of raw SQL to prevent SQL injection
            await db.execute(delete(self.db_model))
            await db.commit()
            return await self._get_all()(
                db=db,
                pagination={"page": 1, "limit": None, "skip": 0, "order_by": None},
                filters=None,
                contextual_filters={},
                user=None,
            )

        return route

    def _delete_one(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Delete one item by ID (soft delete or hard delete based on configuration)"""

        async def route(
            item_id: self._pk_type,  # type: ignore[name-defined]
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> None:
            # Permission check
            if (
                self.permission_checker
                and "delete_one" in self.permissions
                and user
                and not self.permission_checker(user, self.permissions["delete_one"])
            ):
                raise HTTPException(403, "No permission to delete resources")

            # Access check
            if self.access_checker and user:
                await self.access_checker(item_id, user, db)

            # Verify item exists first
            db_model = await db.get(self.db_model, item_id)  # type: ignore[arg-type]
            if not db_model:
                raise NOT_FOUND from None

            # Check if item is already soft-deleted (if soft delete is enabled)
            if self.soft_delete:
                soft_delete_col_value = getattr(db_model, self.soft_delete_field, None)
                if soft_delete_col_value == self.soft_delete_value:
                    raise NOT_FOUND from None

            # Business validation before delete
            if self.delete_validator:
                await self.delete_validator(item_id, user, db)

            if self.soft_delete:
                # Soft delete: update the soft delete fields
                setattr(db_model, self.soft_delete_field, self.soft_delete_value)

                # Set timestamp if configured
                if self.soft_delete_timestamp_field:
                    setattr(
                        db_model,
                        self.soft_delete_timestamp_field,
                        datetime.now(timezone.utc),
                    )

                # Set deleted_by if configured and user is available
                if self.soft_delete_by_field and user:
                    user_id = getattr(user, "id", None)
                    if user_id:
                        setattr(db_model, self.soft_delete_by_field, user_id)

                await db.commit()
            else:
                # Hard delete: remove the item from database
                await db.delete(db_model)
                await db.commit()

            # Call after_delete hook (after commit)
            if self.after_delete:
                try:
                    await self.after_delete(item_id, user, db)
                except Exception as hook_error:  # pylint: disable=broad-except
                    # Log hook errors but don't fail the main operation
                    self._logger.error(f"after_delete hook error: {hook_error}")

        return route

    # ==================== BULK OPERATIONS ====================

    def _bulk_create(self) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        """Bulk create multiple items

        Returns:
            Dict with 'created' list, 'errors' list, 'success_count', 'error_count'
        """

        async def route(
            items: List[self.create_schema],  # type: ignore[name-defined]
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> dict[str, Any]:
            # Check max items limit
            if len(items) > self.bulk_max_items:
                raise HTTPException(
                    400,
                    f"Too many items. Maximum allowed: {self.bulk_max_items}",
                )

            # Permission check
            self._check_permission(user, "create")

            # Bulk validation (validates entire batch before processing)
            if self.bulk_create_validator and user:
                items_as_dicts = [item.model_dump() for item in items]
                await self.bulk_create_validator(items_as_dicts, user, db)

            created_items: List[Any] = []
            errors: List[dict[str, Any]] = []

            for idx, item in enumerate(items):  # pylint: disable=too-many-nested-blocks
                try:
                    # Apply create_defaults
                    if self.create_defaults and user:
                        defaults = self.create_defaults(user)
                        if defaults:
                            item_data = item.model_dump()
                            item_fields_set = item.model_fields_set
                            merged_data = {**defaults}
                            for key, value in item_data.items():
                                if key in item_fields_set or key not in merged_data:
                                    merged_data[key] = value
                            item = self.create_schema(**merged_data)

                    # Business validation
                    if self.create_validator and user:
                        item = await self.create_validator(item, user, db)

                    # Create the item
                    db_model: Model = self.db_model(**item.model_dump())
                    db.add(db_model)
                    await db.flush()  # Get the ID without committing

                    created_items.append(
                        {
                            "index": idx,
                            self._pk: getattr(db_model, self._pk),
                            "data": item.model_dump(),
                        }
                    )

                    # Call after_create hook (ignore errors to not fail bulk operation)
                    if self.after_create:
                        try:  # noqa: SIM105
                            await self.after_create(db_model, user, db)
                        except Exception:  # pylint: disable=broad-except
                            pass

                except Exception as e:  # pylint: disable=broad-except
                    errors.append(
                        {
                            "index": idx,
                            "error": str(e),
                            "data": item.model_dump()
                            if hasattr(item, "model_dump")
                            else {},
                        }
                    )
                    if not self.bulk_partial_success:
                        await db.rollback()
                        raise HTTPException(
                            400, f"Bulk create failed at index {idx}: {e}"
                        ) from e

            # Commit all successful creations
            if created_items:
                await db.commit()

            return {
                "created": created_items,
                "errors": errors,
                "success_count": len(created_items),
                "error_count": len(errors),
            }

        return route

    def _bulk_update(self) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        """Bulk update multiple items

        Input format: List of objects with 'id' (or pk field name) and fields to update
        Returns:
            Dict with 'updated' list, 'errors' list, 'success_count', 'error_count'
        """

        async def route(
            items: List[dict[str, Any]],
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> dict[str, Any]:
            # Check max items limit
            if len(items) > self.bulk_max_items:
                raise HTTPException(
                    400,
                    f"Too many items. Maximum allowed: {self.bulk_max_items}",
                )

            # Permission check
            self._check_permission(user, "update")

            updated_items: List[dict[str, Any]] = []
            errors: List[dict[str, Any]] = []

            for idx, item_data in enumerate(items):
                try:
                    # Get the item ID
                    item_id = item_data.get(self._pk) or item_data.get("id")
                    if item_id is None:
                        raise ValueError(f"Missing '{self._pk}' in item at index {idx}")

                    # Access check
                    if self.access_checker and user:
                        await self.access_checker(item_id, user, db)

                    # Get the item from database
                    db_model = await db.get(
                        self.db_model,  # type: ignore[arg-type]
                        item_id,
                    )
                    if not db_model:
                        raise ValueError(f"Item with {self._pk}={item_id} not found")

                    # Update fields (exclude pk)
                    update_data = {
                        k: v
                        for k, v in item_data.items()
                        if k not in {self._pk, "id"} and hasattr(db_model, k)
                    }

                    for key, value in update_data.items():
                        setattr(db_model, key, value)

                    await db.flush()

                    updated_items.append(
                        {
                            "index": idx,
                            self._pk: item_id,
                            "updated_fields": list(update_data.keys()),
                        }
                    )

                    # Call after_update hook (ignore errors to not fail bulk operation)
                    if self.after_update:
                        try:  # noqa: SIM105
                            await self.after_update(db_model, user, db)
                        except Exception:  # pylint: disable=broad-except
                            pass

                except Exception as e:  # pylint: disable=broad-except
                    errors.append(
                        {
                            "index": idx,
                            "error": str(e),
                            self._pk: item_data.get(self._pk) or item_data.get("id"),
                        }
                    )
                    if not self.bulk_partial_success:
                        await db.rollback()
                        raise HTTPException(
                            400, f"Bulk update failed at index {idx}: {e}"
                        ) from e

            # Commit all successful updates
            if updated_items:
                await db.commit()

            return {
                "updated": updated_items,
                "errors": errors,
                "success_count": len(updated_items),
                "error_count": len(errors),
            }

        return route

    def _bulk_delete(self) -> Callable[..., Coroutine[Any, Any, dict[str, Any]]]:
        """Bulk delete multiple items

        Input format: List of IDs to delete
        Returns:
            Dict with 'deleted_ids' list, 'errors' list, 'success_count', 'error_count'
        """

        async def route(
            ids: List[Any],
            db: AsyncSession = Depends(self.db_func),
            user: Any = self.current_user_depends,
        ) -> dict[str, Any]:
            # Check max items limit
            if len(ids) > self.bulk_max_items:
                raise HTTPException(
                    400,
                    f"Too many items. Maximum allowed: {self.bulk_max_items}",
                )

            # Permission check
            self._check_permission(user, "delete_one")

            deleted_ids: List[Any] = []
            errors: List[dict[str, Any]] = []

            for idx, item_id in enumerate(ids):
                try:
                    # Access check
                    if self.access_checker and user:
                        await self.access_checker(item_id, user, db)

                    # Get the item
                    db_model = await db.get(
                        self.db_model,  # type: ignore[arg-type]
                        item_id,
                    )
                    if not db_model:
                        raise ValueError(f"Item with {self._pk}={item_id} not found")

                    # Check if already soft-deleted
                    if self.soft_delete:
                        soft_delete_col_value = getattr(
                            db_model, self.soft_delete_field, None
                        )
                        if soft_delete_col_value == self.soft_delete_value:
                            raise ValueError(f"Item {item_id} already deleted")

                    # Business validation
                    if self.delete_validator:
                        await self.delete_validator(item_id, user, db)

                    # Perform delete (soft or hard)
                    if self.soft_delete:
                        setattr(
                            db_model, self.soft_delete_field, self.soft_delete_value
                        )
                        if self.soft_delete_timestamp_field:
                            setattr(
                                db_model,
                                self.soft_delete_timestamp_field,
                                datetime.now(timezone.utc),
                            )
                        if self.soft_delete_by_field and user:
                            user_id = getattr(user, "id", None)
                            if user_id:
                                setattr(db_model, self.soft_delete_by_field, user_id)
                    else:
                        await db.delete(db_model)

                    await db.flush()
                    deleted_ids.append(item_id)

                    # Call after_delete hook (ignore errors to not fail bulk operation)
                    if self.after_delete:
                        try:  # noqa: SIM105
                            await self.after_delete(item_id, user, db)
                        except Exception:  # pylint: disable=broad-except
                            pass

                except Exception as e:  # pylint: disable=broad-except
                    errors.append(
                        {
                            "index": idx,
                            self._pk: item_id,
                            "error": str(e),
                        }
                    )
                    if not self.bulk_partial_success:
                        await db.rollback()
                        raise HTTPException(
                            400, f"Bulk delete failed at index {idx}: {e}"
                        ) from e

            # Commit all successful deletes
            if deleted_ids:
                await db.commit()

            return {
                "deleted_ids": deleted_ids,
                "errors": errors,
                "success_count": len(deleted_ids),
                "error_count": len(errors),
            }

        return route
