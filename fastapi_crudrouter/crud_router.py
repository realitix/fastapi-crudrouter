from copy import deepcopy
from datetime import date, datetime
import math
from types import UnionType
from typing import (
    Annotated,
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

# Import Pydantic string-like types for filter generation
try:
    from pydantic import AnyUrl, EmailStr, HttpUrl

    PYDANTIC_STRING_TYPES: tuple = (EmailStr, AnyUrl, HttpUrl)
except ImportError:
    # If specific types aren't available, use empty tuple
    PYDANTIC_STRING_TYPES = ()

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


def get_pk_type(schema: Type[BaseModel], pk_field: str) -> Any:
    """Extract primary key type from schema"""
    try:
        field_annotation = schema.model_fields[pk_field].annotation
        return field_annotation if field_annotation is not None else int
    except (KeyError, AttributeError):
        return int


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


def schema_factory(
    schema_cls: Type[BaseModel], pk_field_name: str = "id", name: str = "Create"
) -> Type[BaseModel]:
    """Create schema without primary key for create/update operations"""
    fields: dict[str, Any] = {}
    for field_name, field_info in schema_cls.model_fields.items():
        if field_name != pk_field_name:
            if field_info.default is not None:
                fields[field_name] = (field_info.annotation, field_info.default)
            else:
                fields[field_name] = (field_info.annotation, ...)

    return create_model(f"{schema_cls.__name__}{name}", **fields)


def optional_schema_factory(
    schema_cls: Type[BaseModel], pk_field_name: str = "id", name: str = "Patch"
) -> Type[BaseModel]:
    """Create schema with all fields optional for partial updates (PATCH)

    Preserves all validators and FieldInfo metadata (aliases, constraints, etc.).
    """
    fields = {}
    for field_name, field_info in schema_cls.model_fields.items():
        if field_name != pk_field_name:
            # Deep copy the original FieldInfo to preserve all metadata
            # (alias, validation_alias, constraints, description, etc.)
            new_field_info = deepcopy(field_info)

            # Modify only what's needed for PATCH: make it optional with None default
            new_field_info.default = None
            new_field_info.default_factory = None

            fields[field_name] = (Optional[field_info.annotation], new_field_info)

    # Create new model with __base__ to inherit validators
    new_model = create_model(  # type: ignore[call-overload]
        f"{schema_cls.__name__}{name}",
        __base__=schema_cls,
        __module__=schema_cls.__module__,
        **fields,
    )

    return new_model


def is_optional_type(annotation: Any) -> bool:
    """Check if a type annotation is Optional (Union with None)"""
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = get_args(annotation)
        return type(None) in args
    return False


def extract_python_type(field_type: Any) -> Any:
    """Extract base type from Optional types and Annotated types"""
    origin = get_origin(field_type)
    if origin is None:
        return field_type

    # Handle Annotated types: Annotated[T, metadata] -> T
    if origin is Annotated:
        args = get_args(field_type)
        if args:
            # Recursively extract in case we have Annotated[Optional[T], ...]
            return extract_python_type(args[0])

    args = get_args(field_type)
    if (
        (origin is UnionType or origin is Union)
        and len(args) == 2
        and type(None) in args
    ):
        # Get the non-None type and recursively extract
        # (in case it's Annotated)
        non_none_type = next(arg for arg in args if arg is not type(None))
        return extract_python_type(non_none_type)

    return origin


def _is_string_like_type(field_type: Any) -> bool:
    """Check if a type is string or string-like (EmailStr, HttpUrl, etc.)

    Returns True for:
    - str (base Python type)
    - Pydantic string types (EmailStr, HttpUrl, AnyUrl, etc.)
    """
    # Check for base str type
    if field_type is str:
        return True

    # Check for known Pydantic string types
    if PYDANTIC_STRING_TYPES and isinstance(field_type, type):
        try:
            if issubclass(field_type, PYDANTIC_STRING_TYPES):
                return True
        except TypeError:
            # Some types like Annotated[] can't be used with issubclass
            pass

    # Fallback: check if type name suggests it's a string type
    # This catches custom string validators and other Pydantic string types
    if hasattr(field_type, "__name__"):
        name = field_type.__name__
        if "Str" in name or "Email" in name or "Url" in name or "Uri" in name:
            return True

    return False


def generate_fields_with_suffixes(base_fields: dict[str, Any]) -> dict[str, Any]:
    """Generate filter fields with special operators"""
    new_fields = {}
    for field_name, field_info in base_fields.items():
        # Skip operator fields (ending with __like, __gte, __lte)
        if field_name.endswith(("__like", "__gte", "__lte")):
            continue

        field_type = extract_python_type(field_info.annotation)
        if field_type in (date, datetime):
            lte = f"{field_name}__lte"
            if lte not in base_fields:
                new_fields[lte] = (Optional[field_type], None)

            gte = f"{field_name}__gte"
            if gte not in base_fields:
                new_fields[gte] = (Optional[field_type], None)

        elif _is_string_like_type(field_type):
            like = f"{field_name}__like"
            if like not in base_fields:
                new_fields[like] = (Optional[str], None)

    return new_fields


def create_filter(base_model: type[PYDANTIC_SCHEMA]) -> type[PYDANTIC_SCHEMA]:
    """Create filter schema with special operators"""
    base_fields = base_model.model_fields
    dynamic_fields = generate_fields_with_suffixes(base_fields)

    return create_model(  # type: ignore[call-overload]
        base_model.__name__,
        __base__=base_model,
        **{
            name: (annotation, default)
            for name, (annotation, default) in dynamic_fields.items()
        },
    )


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

    def __init__(  # pylint: disable=too-many-positional-arguments
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
        self.schema = schema
        self.db_model = db_model
        self.db_func = db
        self.raise_callback = raise_callback
        self.paginate_limit = paginate

        # Store security hooks
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

        # Set up primary key with validation
        pk_columns = db_model.__table__.primary_key.columns.keys()  # type: ignore[union-attr]
        if not pk_columns:
            raise ValueError(
                f"Model {db_model.__name__} must have a primary key. "
                "CRUDRouter requires a primary key column."
            )
        self._pk: str = pk_columns[0]
        self._pk_type: Any = get_pk_type(schema, self._pk)

        # Set up schemas
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

        # Set up filtering with auto-generated fields from schema
        auto_filter_fields = {}

        # Generate automatic filter fields from schema
        # (all fields become optional filters)
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

        # Set up pagination
        self.pagination = pagination_factory(max_limit=paginate)

        # Check if any routes are enabled (routes can be False or dependencies list)
        def is_route_enabled(route):
            return route is not False and route is not None

        routes_enabled = any(
            [
                is_route_enabled(get_all_route),
                is_route_enabled(get_all_options_route),
                is_route_enabled(get_one_route),
                is_route_enabled(create_route),
                is_route_enabled(update_route),
                is_route_enabled(delete_one_route),
                is_route_enabled(delete_all_route),
            ]
        )

        # Set up router only if routes are enabled
        if routes_enabled:
            table_name = db_model.__tablename__  # type: ignore[union-attr]
            prefix = str(prefix if prefix else table_name).lower()
            prefix = "/" + prefix.strip("/")
            tags_list: Any = tags or [prefix.strip("/").capitalize()]
            super().__init__(prefix=prefix, tags=tags_list, **kwargs)
        else:
            # Initialize router with empty prefix if no routes are enabled
            super().__init__(prefix="", **kwargs)

        # Only set up response models and routes if any routes are enabled
        if routes_enabled:
            # Set up response models
            class PaginationResultModel(BaseModel):
                total_records: int
                total_pages: int
                current_page: int

            class GetAllResponseModel(BaseModel):
                pagination: PaginationResultModel
                data: list[self.get_all_schema]  # type: ignore

            # Add routes
            if get_all_route:
                # Always use pagination response model
                self._add_api_route(
                    "",
                    self._get_all(),
                    methods=["GET"],
                    response_model=GetAllResponseModel,
                    summary="Get All",
                    dependencies=get_all_route,
                )

            if get_all_options_route:
                self._add_api_route(
                    "",
                    self._get_all_options,
                    methods=["OPTIONS"],
                    response_model=dict[str, Any],
                    summary="Get All Schema",
                    dependencies=get_all_options_route,
                )

            if create_route:
                self._add_api_route(
                    "",
                    self._create(),
                    methods=["POST"],
                    response_model=schema,
                    summary="Create One",
                    status_code=201,
                    dependencies=create_route,
                )

            if delete_all_route:
                # Always use pagination response model
                self._add_api_route(
                    "",
                    self._delete_all(),
                    methods=["DELETE"],
                    response_model=GetAllResponseModel,
                    summary="Delete All",
                    dependencies=delete_all_route,
                )

            if get_one_route:
                self._add_api_route(
                    "/{item_id}",
                    self._get_one(),
                    methods=["GET"],
                    response_model=schema,
                    summary="Get One",
                    dependencies=get_one_route,
                    error_responses=[NOT_FOUND],
                )

            if update_route:
                # PUT route - full replacement
                self._add_api_route(
                    "/{item_id}",
                    self._update(),
                    methods=["PUT"],
                    response_model=schema,
                    summary="Update One",
                    dependencies=update_route,
                    error_responses=[NOT_FOUND],
                )

                # PATCH route - partial update
                self._add_api_route(
                    "/{item_id}",
                    self._patch(),
                    methods=["PATCH"],
                    response_model=schema,
                    summary="Partially Update One",
                    dependencies=update_route,
                    error_responses=[NOT_FOUND],
                )

            if delete_one_route:
                self._add_api_route(
                    "/{item_id}",
                    self._delete_one(),
                    methods=["DELETE"],
                    response_model=None,
                    summary="Delete One",
                    status_code=204,
                    dependencies=delete_one_route,
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
        """Overrides and exiting route if it exists"""
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
        """Compute subdata for list joins"""
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
            page, limit = pagination.get("page", 1), pagination.get("limit")
            # Use skip directly if provided, otherwise calculate from page
            skip = pagination.get("skip", 0)
            if skip == 0:
                skip = (page - 1) * limit if limit else 0

            # Permission check
            if (
                self.permission_checker
                and "get_all" in self.permissions
                and user
                and not self.permission_checker(user, self.permissions["get_all"])
            ):
                raise HTTPException(403, "No permission to view resources")

            base_class_fields, join_fields, join_list_fields, custom_func_fields = (
                self.get_fields(self.get_all_schema)
            )

            query = select(*base_class_fields)
            query = self.compute_query_join(query, join_fields)
            query = self.compute_custom_func(query, custom_func_fields)

            def special_filter(query_src: Any, k: str, v: Any):
                filter_key, filter_op = k.split("__")
                if filter_op == "gte":
                    query_src = query_src.where(getattr(self.db_model, filter_key) >= v)
                elif filter_op == "lte":
                    query_src = query_src.where(getattr(self.db_model, filter_key) <= v)
                elif filter_op == "like":
                    query_src = query_src.where(
                        getattr(self.db_model, filter_key).ilike(f"%{v}%")
                    )
                elif filter_op == "in":
                    query_src = query_src.where(
                        getattr(self.db_model, filter_key).in_(v)
                    )
                return query_src

            def query_where(query_src: Any) -> Any:
                # Apply contextual filters first
                if contextual_filters and isinstance(contextual_filters, dict):
                    for k, v in contextual_filters.items():
                        if v is None:
                            continue
                        if "__" in k:
                            query_src = special_filter(query_src, k, v)
                        else:
                            query_src = query_src.where(getattr(self.db_model, k) == v)

                # Apply user filters
                if filters and filters is not None:
                    # Handle case where filters is a Pydantic model
                    if hasattr(filters, "model_dump"):
                        filter_dict = filters.model_dump()
                    elif isinstance(filters, dict):
                        filter_dict = filters
                    else:
                        # Skip filtering if filters is not a proper object
                        return query_src

                    for k, v in filter_dict.items():
                        if v is None:
                            continue

                        metadata = self._get_filter_metadata(k)

                        if callable(metadata):
                            query_src = metadata(query_src, v)
                        elif metadata:
                            query_src = query_src.join(metadata.class_).where(
                                metadata == v
                            )
                        elif "__" in k:
                            query_src = special_filter(query_src, k, v)
                        else:
                            query_src = query_src.where(getattr(self.db_model, k) == v)
                return query_src

            query = query_where(query).select_from(self.db_model)
            # pylint: disable=not-callable
            query_count = query.with_only_columns(func.count()).select_from(
                self.db_model
            )

            def get_order_by() -> Any:
                order_by = pagination.get("order_by")
                if not order_by:
                    return desc(getattr(self.db_model, self._pk))

                order_by = order_by.split("__")
                if len(order_by) == 2:
                    order_by_field, order_by_direction = order_by
                else:
                    order_by_field = order_by[0]
                    order_by_direction = "ASC"

                # Validation: Reject private/dunder attributes (security)
                if order_by_field.startswith("_"):
                    return desc(getattr(self.db_model, self._pk))

                # Validation: Check that field exists
                if not hasattr(self.db_model, order_by_field):
                    return desc(getattr(self.db_model, self._pk))

                field_attr = getattr(self.db_model, order_by_field)

                # Validation: Only allow valid directions
                if order_by_direction not in ("ASC", "DESC"):
                    order_by_direction = "ASC"

                if order_by_direction == "DESC":
                    return desc(field_attr)

                return field_attr

            result = await db.execute(
                query.order_by(get_order_by()).limit(limit).offset(skip)
            )
            rows = result.all()

            db_models: List[Model] = []
            for row in rows:
                # pylint: disable=protected-access
                row_dict = (
                    row._asdict() if hasattr(row, "_asdict") else dict(row._mapping)
                )
                pk_value = row_dict.get(self._pk, getattr(row, self._pk, None))
                subdata = await self.compute_subdata(db, pk_value, join_list_fields)
                model = self.get_all_schema(**row_dict, **subdata)
                db_models.append(model)

            count_result = (await db.execute(query_count)).first()
            count = count_result[0] if count_result else 0

            # Always return pagination format
            return {
                "pagination": {
                    "total_records": count,
                    "total_pages": math.ceil(count / limit) if limit else 1,
                    "current_page": page,
                },
                "data": db_models,
            }

        return route

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

            # Validation métier
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

            # Validation métier (optionnel)
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

            # Validation métier (optionnel)
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
