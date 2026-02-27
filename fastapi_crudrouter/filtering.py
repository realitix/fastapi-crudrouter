"""Filtering logic for CRUD operations"""

from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional, Type, Union

from pydantic import BaseModel
from sqlalchemy import Select, and_, desc, literal_column, or_
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.orm import InstrumentedAttribute

if TYPE_CHECKING:
    from sqlalchemy.orm import DeclarativeBase


class FilterOperator(str, Enum):
    """Supported filter operators"""

    EQ = "eq"  # Equal (default)
    GTE = "gte"  # Greater than or equal
    LTE = "lte"  # Less than or equal
    LIKE = "like"  # Pattern matching (case-insensitive)
    IN = "in"  # Value in list


class FilterBuilder:
    """Builds SQLAlchemy WHERE clauses from filters"""

    def __init__(self, model: Union[Type["DeclarativeBase"], DeclarativeMeta]):
        """Initialize filter builder.

        Args:
            model: SQLAlchemy model class to filter
        """
        self.model = model
        self._operator_handlers = {
            FilterOperator.GTE: self._handle_gte,
            FilterOperator.LTE: self._handle_lte,
            FilterOperator.LIKE: self._handle_like,
            FilterOperator.IN: self._handle_in,
        }

    def apply_filters(
        self,
        query: Select,
        filters: Optional[BaseModel],
        contextual_filters: Optional[dict] = None,
        filter_metadata_getter: Optional[Callable[[str], Any]] = None,
    ) -> Select:
        """Apply filters to a SQLAlchemy query.

        Args:
            query: Base SELECT query
            filters: Pydantic model with filter values
            contextual_filters: Dict of implicit filters (e.g., user context)
            filter_metadata_getter: Function to get metadata for filter fields

        Returns:
            Modified query with WHERE clauses added

        Examples:
            >>> builder = FilterBuilder(User)
            >>> query = select(User)
            >>> filters = UserFilter(name="John", age__gte=18)
            >>> query = builder.apply_filters(query, filters)
        """
        # Apply contextual filters first
        if contextual_filters:
            query = self._apply_dict_filters(query, contextual_filters, None)

        # Apply user filters
        if filters:
            if hasattr(filters, "model_dump"):
                filter_dict = filters.model_dump()
            else:
                filter_dict = filters  # type: ignore[assignment]
            query = self._apply_dict_filters(query, filter_dict, filter_metadata_getter)

        return query.select_from(self.model)

    def _apply_dict_filters(
        self,
        query: Select,
        filter_dict: dict,
        filter_metadata_getter: Optional[Callable[[str], Any]],
    ) -> Select:
        """Apply filters from a dictionary"""
        for key, value in filter_dict.items():
            if value is None:
                continue

            # Handle logical operators __or__ and __and__
            if key == "__or__" and isinstance(value, list):
                conditions = self._build_conditions_from_list(value)
                if conditions:
                    query = query.where(or_(*conditions))
                continue
            if key == "__and__" and isinstance(value, list):
                conditions = self._build_conditions_from_list(value)
                if conditions:
                    query = query.where(and_(*conditions))
                continue

            # Check for metadata (custom filter function or join)
            metadata = None
            if filter_metadata_getter:
                metadata = filter_metadata_getter(key)

            if callable(metadata):
                # Custom filter function
                query = metadata(query, value)
            elif metadata:
                # Join-based filter
                query = query.join(metadata.class_).where(metadata == value)
            elif "__" in key:
                # Operator-based filter
                query = self._apply_operator_filter(query, key, value)
            else:
                # Simple equality filter
                query = query.where(getattr(self.model, key) == value)

        return query

    def _build_conditions_from_list(self, conditions_list: list) -> list:
        """Build SQLAlchemy conditions from a list of filter dicts.

        Args:
            conditions_list: List of filter dicts, e.g., [{"school_id": None}, {"school_id": 1}]

        Returns:
            List of SQLAlchemy comparison expressions
        """
        conditions = []
        for cond_dict in conditions_list:
            if not isinstance(cond_dict, dict):
                continue
            for field, value in cond_dict.items():
                if hasattr(self.model, field):
                    col = getattr(self.model, field)
                    if value is None:
                        conditions.append(col.is_(None))
                    else:
                        conditions.append(col == value)
        return conditions

    def _apply_operator_filter(self, query: Select, key: str, value: Any) -> Select:
        """Apply filter with operator (__gte, __lte, etc.)"""
        field_name, operator = key.split("__", 1)

        try:
            operator_enum = FilterOperator(operator)
            handler = self._operator_handlers.get(operator_enum)
            if handler:
                return handler(query, field_name, value)
        except ValueError:
            # Unknown operator, treat as field name with __
            pass

        # If operator not recognized, return query unchanged (ignore unknown operators)
        return query

    def _handle_gte(self, query: Select, field: str, value: Any) -> Select:
        """Handle >= operator"""
        return query.where(getattr(self.model, field) >= value)

    def _handle_lte(self, query: Select, field: str, value: Any) -> Select:
        """Handle <= operator"""
        return query.where(getattr(self.model, field) <= value)

    def _handle_like(self, query: Select, field: str, value: Any) -> Select:
        """Handle LIKE operator (case-insensitive pattern matching)"""
        return query.where(getattr(self.model, field).ilike(f"%{value}%"))

    def _handle_in(self, query: Select, field: str, value: Any) -> Select:
        """Handle IN operator.

        Accepts:
        - Lists/tuples/sets: used directly
        - Comma-separated strings: split into a list (e.g., "ACTIVE,PENDING")
        - Single values: converted to single-item lists

        Values are automatically cast to match the column's Python type
        (e.g., string "4" becomes int 4 for integer columns).

        This allows URL parameters like:
        - ?status__in=ACTIVE (single value)
        - ?status__in=ACTIVE,PENDING (comma-separated)
        - ?teacher_id__in=4,5 (numeric comma-separated)

        Args:
            query: SQLAlchemy Select query
            field: Model field name to filter on
            value: Filter value(s)

        Returns:
            Query with IN clause applied
        """
        # Handle different input types
        if isinstance(value, (list, tuple, set)):
            # Already a collection, use as-is
            values = list(value)
        elif isinstance(value, str) and "," in value:
            # Comma-separated string: split and strip whitespace
            values = [v.strip() for v in value.split(",") if v.strip()]
        else:
            # Single value: wrap in list
            values = [value]

        # Cast values to match the column's Python type (e.g., str -> int)
        column = getattr(self.model, field)
        try:
            col_python_type = column.property.columns[0].type.python_type
            if col_python_type in (int, float):
                values = [col_python_type(v) for v in values]
        except (AttributeError, NotImplementedError, ValueError):
            pass  # Keep values as-is if type detection fails

        return query.where(column.in_(values))


class OrderByBuilder:
    """Builds SQLAlchemy ORDER BY clauses"""

    def __init__(
        self,
        model: Union[Type["DeclarativeBase"], DeclarativeMeta],
        default_pk: str,
        default_order_by: Optional[str] = None,
    ):
        """Initialize order by builder.

        Args:
            model: SQLAlchemy model class
            default_pk: Default primary key field for ordering
            default_order_by: Custom default ordering (e.g., "display_order" or
                "created_at__DESC"). If not provided, defaults to pk DESC.
        """
        self.model = model
        self.default_pk = default_pk
        self.default_order_by = default_order_by
        self._computed_columns: set[str] = set()

    def set_computed_columns(self, columns: set[str]) -> None:
        """Set the list of computed column names that can be sorted on.

        Computed columns are columns added to the query via add_columns()
        in custom functions (e.g., Annotated[date, join_function]).

        Args:
            columns: Set of computed column names
        """
        self._computed_columns = columns

    def get_order_by(self, order_by_param: Optional[str]) -> Any:
        """Get ORDER BY clause from parameter.

        Args:
            order_by_param: Order by parameter (e.g., "name__DESC")

        Returns:
            SQLAlchemy order by expression

        Examples:
            >>> builder = OrderByBuilder(User, "id")
            >>> order = builder.get_order_by("name__DESC")
            >>> # Returns: desc(User.name)
            >>> order = builder.get_order_by("age")
            >>> # Returns: User.age
            >>> order = builder.get_order_by(None)
            >>> # Returns: desc(User.id) or default_order_by if configured
        """
        # If no order_by param provided, use default_order_by or fallback to pk DESC
        if not order_by_param:
            if self.default_order_by:
                return self._parse_order_by(self.default_order_by)
            return desc(getattr(self.model, self.default_pk))

        return self._parse_order_by(order_by_param)

    def _parse_order_by(self, order_by_str: str) -> Any:
        """Parse order_by string and return SQLAlchemy expression.

        Args:
            order_by_str: Order by string (e.g., "name__DESC", "age")

        Returns:
            SQLAlchemy order by expression
        """
        parts = order_by_str.split("__")
        if len(parts) == 2:
            field_name, direction = parts
        else:
            field_name = parts[0]
            direction = "ASC"

        # Security: Reject private/dunder attributes
        if field_name.startswith("_"):
            return desc(getattr(self.model, self.default_pk))

        # Validate direction
        if direction not in ("ASC", "DESC"):
            direction = "ASC"

        # Check if it's a computed column (added via add_columns in custom functions)
        if field_name in self._computed_columns:
            computed_col: Any = literal_column(field_name)
            return desc(computed_col) if direction == "DESC" else computed_col

        # Validate field exists on the model
        if not hasattr(self.model, field_name):
            return desc(getattr(self.model, self.default_pk))

        field_attr = getattr(self.model, field_name)

        # Verify it's a column
        if not isinstance(field_attr, InstrumentedAttribute):
            return desc(getattr(self.model, self.default_pk))

        return desc(field_attr) if direction == "DESC" else field_attr
