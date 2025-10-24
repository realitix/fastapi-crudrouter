import math
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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.types import DecoratedCallable
from pydantic import BaseModel, create_model

from .schema_factory import (
    create_filter,
    get_pk_type,
    is_optional_type,
    optional_schema_factory,
    schema_factory,
)

try:
    from sqlalchemy import delete, desc, func
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
    """Create pagination dependency"""

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
    """Find join condition between tables"""
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
    total_records: int
    total_pages: int
    current_page: int


class GetAllResult(TypedDict):
    pagination: PaginationResult
    data: list[Model]


class CRUDRouter(APIRouter):  # pylint: disable=too-many-instance-attributes
    """Simplified CRUD Router for SQLAlchemy async only"""

    def __init__(  # pylint: disable=too-many-positional-arguments,super-init-not-called
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
        **kwargs: Any,
    ) -> None:
        # 1. Initialize base attributes
        self._init_base_attributes(schema, db_model, db, raise_callback, paginate)

        # 2. Initialize security hooks
        self._init_security_hooks(
            current_user_dependency,
            contextual_filter,
            access_checker,
            permission_checker,
            permissions,
            create_validator,
            update_validator,
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
    ) -> None:
        """Initialize basic attributes"""
        self.schema = schema
        self.db_model = db_model
        self.db_func = db
        self.raise_callback = raise_callback
        self.paginate_limit = paginate

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

    def _init_security_hooks(  # pylint: disable=too-many-positional-arguments
        self,
        current_user_dependency: Optional[Callable],
        contextual_filter: Optional[Callable],
        access_checker: Optional[Callable],
        permission_checker: Optional[Callable],
        permissions: Optional[dict[str, Any]],
        create_validator: Optional[Callable],
        update_validator: Optional[Callable],
    ) -> None:
        """Initialize security hooks and validators"""
        self.access_checker = access_checker
        self.permission_checker = permission_checker
        self.permissions = permissions or {}
        self.create_validator = create_validator
        self.update_validator = update_validator

        # Wrap hooks in Depends() for FastAPI injection
        if current_user_dependency:
            self.current_user_depends = Depends(current_user_dependency)
        else:
            self.current_user_depends = None

        if contextual_filter:
            self.contextual_filter_depends = Depends(contextual_filter)
        else:
            self.contextual_filter_depends = Depends(lambda: {})

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
                "/{item_id}",
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
                "/{item_id}",
                self._update(),
                methods=["PUT"],
                response_model=self.schema,
                summary="Update One",
                dependencies=route_config["update"],
                error_responses=[NOT_FOUND],
            )

            # PATCH route - partial update
            self._add_api_route(
                "/{item_id}",
                self._patch(),
                methods=["PATCH"],
                response_model=self.schema,
                summary="Partially Update One",
                dependencies=route_config["update"],
                error_responses=[NOT_FOUND],
            )

        if route_config["delete_one"]:
            self._add_api_route(
                "/{item_id}",
                self._delete_one(),
                methods=["DELETE"],
                response_model=None,
                summary="Delete One",
                status_code=204,
                dependencies=route_config["delete_one"],
                error_responses=[NOT_FOUND],
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

        for route in self.routes:
            if (
                route.path == f"{self.prefix}{path}"  # type: ignore
                and route.methods == methods_  # type: ignore
            ):
                self.routes.remove(route)

    def _get_filter_metadata(self, filter_key: str) -> Any:
        """Get metadata for filter field"""
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
        """Parse schema fields for joins and custom functions"""

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
                    base_class_fields.append(getattr(self.db_model, field))
            else:
                attribute = annotation.metadata[0]
                # Pydantic v2 only
                field_annotation = annotation.annotation
                if get_origin(field_annotation) is list:
                    list_args = get_args(field_annotation)
                    read_cls = list_args[0]
                    foreign_key = attribute[1]
                    join_list_fields[field] = (attribute[0], foreign_key, read_cls)
                elif callable(attribute):
                    custom_func_fields[field] = attribute
                else:
                    join_fields[field] = (attribute, type_can_be_none(field_annotation))

        return base_class_fields, join_fields, join_list_fields, custom_func_fields

    def compute_query_join(self, query, join_fields) -> Any:
        """Add joins to query"""
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
        """Compute subdata for list joins (single model)"""
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

        async def route(
            db: AsyncSession = Depends(self.db_func),
            pagination: PAGINATION = self.pagination,
            filters: self.filter_schema = self.filter_depends,  # type: ignore[name-defined]
            contextual_filters: dict = self.contextual_filter_depends,
            user: Any = self.current_user_depends,
        ) -> GetAllResult:
            # 1. Check permissions
            self._check_permission(user, "get_all")

            # 2. Parse pagination
            page, limit, skip = self._parse_pagination(pagination)

            # 3. Build base query with joins and custom functions
            query, join_list_fields = self._build_base_query(self.get_all_schema)

            # 4. Apply filters
            query = self._apply_filters(query, filters, contextual_filters)

            # 5. Count total records (before ordering - ORDER BY breaks COUNT on PostgreSQL)
            count = await self._count_total(db, query)

            # 6. Apply ordering
            query = query.order_by(self._get_order_by(pagination))

            # 7. Execute query with pagination
            rows = await self._execute_paginated_query(db, query, limit, skip)

            # 8. Process results into models
            db_models = await self._process_results(
                db, rows, self.get_all_schema, join_list_fields
            )

            # 9. Build paginated response
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
        """Apply filters to query"""

        def apply_special_filter(query_src: Any, key: str, value: Any):
            """Apply special filter operators (__gte, __lte, __like, __in)"""
            filter_key, filter_op = key.split("__")
            col = self._get_model_column(filter_key)

            if filter_op == "gte":
                return query_src.where(col >= value)
            if filter_op == "lte":
                return query_src.where(col <= value)
            if filter_op == "like":
                return query_src.where(col.ilike(f"%{value}%"))
            if filter_op == "in":
                return query_src.where(col.in_(value))
            return query_src

        # Apply contextual filters first
        if contextual_filters and isinstance(contextual_filters, dict):
            for k, v in contextual_filters.items():
                if v is None:
                    continue
                if "__" in k:
                    query = apply_special_filter(query, k, v)
                else:
                    col = self._get_model_column(k)
                    query = query.where(col == v)

        # Apply user filters
        if filters:
            filter_dict = (
                filters.model_dump()
                if hasattr(filters, "model_dump")
                else filters
                if isinstance(filters, dict)
                else None
            )

            if filter_dict:
                for k, v in filter_dict.items():
                    if v is None:
                        continue

                    metadata = self._get_filter_metadata(k)

                    if callable(metadata):
                        query = metadata(query, v)
                    elif metadata:
                        query = query.join(metadata.class_).where(metadata == v)
                    elif "__" in k:
                        query = apply_special_filter(query, k, v)
                    else:
                        col = self._get_model_column(k)
                        query = query.where(col == v)

        return query.select_from(self.db_model)

    def _get_order_by(self, pagination: PAGINATION) -> Any:
        """Get order by clause from pagination"""
        order_by = pagination.get("order_by")
        if not order_by:
            return desc(self._get_model_column(self._pk))

        order_by_parts = order_by.split("__")
        if len(order_by_parts) == 2:
            order_by_field, order_by_direction = order_by_parts
        else:
            order_by_field = order_by_parts[0]
            order_by_direction = "ASC"

        # Validation: Reject private/dunder attributes (security)
        if order_by_field.startswith("_"):
            return desc(self._get_model_column(self._pk))

        # Validation: Check that field exists
        if not hasattr(self.db_model, order_by_field):
            return desc(self._get_model_column(self._pk))

        field_attr = self._get_model_column(order_by_field)

        # Validation: Only allow valid directions
        if order_by_direction not in ("ASC", "DESC"):
            order_by_direction = "ASC"

        return desc(field_attr) if order_by_direction == "DESC" else field_attr

    async def _execute_paginated_query(
        self, db: AsyncSession, query: Any, limit: Optional[int], skip: int
    ) -> list:
        """Execute query with pagination"""
        result = await db.execute(query.limit(limit).offset(skip))
        return result.all()

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
        """Build paginated response"""
        return {
            "pagination": {
                "total_records": total_count,
                "total_pages": math.ceil(total_count / limit) if limit else 1,
                "current_page": page,
            },
            "data": data,
        }

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

            # Business validation
            if self.create_validator and user:
                model = await self.create_validator(model, user, db)

            try:
                db_model: Model = self.db_model(**model.model_dump())
                db.add(db_model)
                await db.commit()
                await db.refresh(db_model)
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
                model = await self.update_validator(model, user, db)

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
                model = await self.update_validator(model, user, db)

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
                db=db, pagination={"page": 1, "limit": None}, filters=None
            )

        return route

    def _delete_one(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Delete one item by ID"""

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

            # Delete the item
            await db.delete(db_model)
            await db.commit()

        return route
