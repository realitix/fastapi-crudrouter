"""SQLAlchemy query building utilities"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Type, TypedDict, Union

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.declarative import DeclarativeMeta

if TYPE_CHECKING:
    from sqlalchemy.orm import DeclarativeBase
    from sqlalchemy.sql import Select


class JoinInfo(TypedDict):
    """Information about a join"""

    attribute: Any
    is_outer: bool


class QueryBuilder:
    """Builds SQLAlchemy queries for CRUD operations"""

    def __init__(self, model: Union[Type["DeclarativeBase"], DeclarativeMeta]):
        """Initialize query builder.

        Args:
            model: SQLAlchemy model class
        """
        self.model = model
        self._already_joined: set = set()

    def build_select(
        self,
        fields: List[Any],
        join_fields: Dict[str, JoinInfo],
        custom_functions: Dict[str, Callable],
    ) -> "Select":
        """Build SELECT query with joins and custom functions.

        Args:
            fields: List of column attributes to select
            join_fields: Dict of joins to perform
            custom_functions: Dict of custom query functions

        Returns:
            SQLAlchemy Select query
        """
        query = select(*fields)

        # Apply joins
        query = self._apply_joins(query, join_fields)

        # Apply custom functions
        for func in custom_functions.values():
            query = func(query)

        return query

    def _apply_joins(
        self, query: "Select", join_fields: Dict[str, JoinInfo]
    ) -> "Select":
        """Apply JOIN clauses to query"""
        for label, join_info in join_fields.items():
            attribute = join_info["attribute"]
            is_outer = join_info["is_outer"]

            # Skip if already joined
            if attribute.class_ in self._already_joined:
                continue

            # Find join condition
            join_condition = self._find_join_condition(attribute)

            # Build join arguments
            args = [attribute.class_]
            if join_condition is not None:
                args.append(join_condition)

            # Apply join
            query = query.join(*args, isouter=is_outer)
            self._already_joined.add(attribute.class_)

            # Add column with label
            query = query.add_columns(attribute.label(label))

        return query

    def _find_join_condition(self, target_attr: Any) -> Any:
        """Find join condition between tables"""
        target_cls = target_attr.class_

        from_mapper = sa_inspect(self.model)
        target_mapper = sa_inspect(target_cls)
        target_table_name = target_mapper.local_table.name

        for fk_col in from_mapper.columns:
            for fk in fk_col.foreign_keys:
                referred_col = fk.column
                if referred_col.table.name == target_table_name:
                    return fk_col == referred_col

        return None

    def reset_joins(self) -> None:
        """Reset the set of already-joined tables"""
        self._already_joined.clear()
