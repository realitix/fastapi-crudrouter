"""Schema factory functions for CRUD operations"""

from copy import copy
from datetime import date, datetime
from enum import Enum
from types import UnionType
from typing import Annotated, Any, Optional, Type, Union, get_args, get_origin
import warnings

from pydantic import BaseModel, create_model

# Import Pydantic string-like types for filter generation
try:
    from pydantic import AnyUrl, EmailStr, HttpUrl

    PYDANTIC_STRING_TYPES: tuple = (EmailStr, AnyUrl, HttpUrl)
except ImportError:
    # If specific types aren't available, use empty tuple
    PYDANTIC_STRING_TYPES = ()


def get_pk_type(schema: Type[BaseModel], pk_field: str) -> Any:
    """Extract primary key type from Pydantic schema.

    Unwraps Optional/Union types to get the base type for path converter mapping.

    Args:
        schema: The Pydantic schema to extract from
        pk_field: Name of the primary key field

    Returns:
        The base type annotation of the primary key field (unwrapped from
        Optional/Union), or int if not found

    Examples:
        >>> class User(BaseModel):
        ...     id: int
        ...     name: str
        >>> get_pk_type(User, "id")
        <class 'int'>
        >>> class User(BaseModel):
        ...     id: int | None = None
        ...     name: str
        >>> get_pk_type(User, "id")
        <class 'int'>
    """
    try:
        field_annotation = schema.model_fields[pk_field].annotation
        if field_annotation is not None:
            # Unwrap Optional/Union/Annotated to get base type
            # e.g., int | None -> int, Optional[int] -> int
            return extract_python_type(field_annotation)
        return int
    except (KeyError, AttributeError):
        return int


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
    Uses shallow copy which is faster than deepcopy while preserving all attributes.

    Field shadowing is intentional here - we deliberately override parent fields
    to make them optional for PATCH operations. The warning is suppressed as this
    is the expected behavior for partial update schemas.
    """
    fields = {}
    for field_name, field_info in schema_cls.model_fields.items():
        if field_name != pk_field_name:
            # Shallow copy the FieldInfo - faster than deepcopy and preserves
            # all attributes including metadata (which contains constraints)
            new_field_info = copy(field_info)

            # Modify only what's needed for PATCH: make it optional with None default
            new_field_info.default = None
            new_field_info.default_factory = None

            fields[field_name] = (Optional[field_info.annotation], new_field_info)

    # Suppress field shadowing warnings - the shadowing is intentional
    # We deliberately override parent fields to make them optional for PATCH
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*shadows an attribute in parent.*",
            category=UserWarning,
        )

        # Create new model with __base__ to inherit validators
        new_model = create_model(  # type: ignore[call-overload]
            f"{schema_cls.__name__}{name}",
            __base__=schema_cls,
            __module__=schema_cls.__module__,
            **fields,
        )

    return new_model


def is_optional_type(annotation: Any) -> bool:
    """Check if a type annotation is Optional (Union with None).

    Args:
        annotation: Type annotation to check

    Returns:
        True if annotation is Optional[T] or T | None, False otherwise

    Examples:
        >>> is_optional_type(Optional[str])
        True
        >>> is_optional_type(str | None)
        True
        >>> is_optional_type(str)
        False
    """
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = get_args(annotation)
        return type(None) in args
    return False


def extract_python_type(field_type: Any) -> Any:
    """Extract base type from Optional and Annotated type annotations.

    Recursively unwraps Optional[T] to T and Annotated[T, ...] to T.

    Args:
        field_type: Type annotation to extract from

    Returns:
        The base Python type without Optional or Annotated wrappers

    Examples:
        >>> extract_python_type(Optional[str])
        <class 'str'>
        >>> extract_python_type(Annotated[int, "metadata"])
        <class 'int'>
        >>> extract_python_type(Optional[Annotated[str, "meta"]])
        <class 'str'>
    """
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
    """Check if a type is string or string-like (EmailStr, HttpUrl, etc.).

    Identifies types that should be treated as strings for filtering purposes,
    including Pydantic special string types.

    Args:
        field_type: Type to check

    Returns:
        True for str and Pydantic string types (EmailStr, HttpUrl, AnyUrl),
        False otherwise

    Examples:
        >>> _is_string_like_type(str)
        True
        >>> _is_string_like_type(int)
        False
        >>> _is_string_like_type(EmailStr)  # If available
        True
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


def _is_enum_type(field_type: Any) -> bool:
    """Check if a type is an Enum subclass.

    Args:
        field_type: Type to check

    Returns:
        True if field_type is an Enum subclass, False otherwise
    """
    try:
        return isinstance(field_type, type) and issubclass(field_type, Enum)
    except TypeError:
        return False


def _is_numeric_type(field_type: Any) -> bool:
    """Check if a type is a numeric type (int or float).

    Args:
        field_type: Type to check

    Returns:
        True if field_type is int or float, False otherwise
    """
    try:
        return isinstance(field_type, type) and issubclass(field_type, (int, float))
    except TypeError:
        return False


def generate_fields_with_suffixes(base_fields: dict[str, Any]) -> dict[str, Any]:
    """Generate filter fields with special operators for date, string, and enum types.

    Creates additional filter fields with __gte, __lte operators for date/datetime
    fields, __like operator for string fields, and __in operator for enum and numeric fields.

    Args:
        base_fields: Dictionary of field names to FieldInfo from a Pydantic model

    Returns:
        Dictionary of new field names with operators to (type, default) tuples

    Examples:
        >>> class User(BaseModel):
        ...     name: str
        ...     created_at: date
        ...     status: StatusEnum
        >>> fields = User.model_fields
        >>> generate_fields_with_suffixes(fields)
        {
            'name__like': (Optional[str], None),
            'created_at__gte': (Optional[date], None),
            'created_at__lte': (Optional[date], None),
            'status__in': (Optional[list[StatusEnum]], None)
        }

    Notes:
        - String fields get __like operator for case-insensitive pattern matching
        - Date/datetime fields get __gte and __lte for range filtering
        - Enum fields get __in operator for multi-value filtering
        - Int/float fields get __in operator for multi-value filtering
        - Existing operator fields (already ending in __like, __gte, __lte, __in) are skipped
    """
    new_fields = {}
    for field_name, field_info in base_fields.items():
        # Skip operator fields (ending with __like, __gte, __lte, __in)
        if field_name.endswith(("__like", "__gte", "__lte", "__in")):
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

        elif _is_enum_type(field_type) or _is_numeric_type(field_type):
            # Add __in operator for enum and numeric fields (multi-value filtering)
            # Use str type to accept comma-separated values from URL query params
            # The FilterBuilder._handle_in method will convert the string to a list
            in_field = f"{field_name}__in"
            if in_field not in base_fields:
                new_fields[in_field] = (Optional[str], None)

    return new_fields


def create_filter(base_model: type[BaseModel]) -> type[BaseModel]:
    """Create filter schema with special operators from a base schema.

    Extends a Pydantic model with additional fields for filtering operations.
    Inherits from base_model to preserve validators and metadata.

    Args:
        base_model: Base Pydantic model to extend

    Returns:
        New Pydantic model class with added filter operator fields

    Examples:
        >>> class UserFilter(BaseModel):
        ...     name: Optional[str] = None
        ...     age: Optional[int] = None
        >>> FilterSchema = create_filter(UserFilter)
        >>> # FilterSchema now has: name, age, name__like, age__gte, age__lte
    """
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
