"""Pagination logic and utilities"""

import math
from typing import Any, List, Optional, TypedDict

from fastapi import HTTPException


class PaginationParams(TypedDict):
    """Pagination parameters"""

    page: int
    limit: Optional[int]
    skip: int
    order_by: Optional[str]


class PaginationMeta(TypedDict):
    """Pagination metadata"""

    total_records: int
    total_pages: int
    current_page: int


class PaginationValidator:
    """Validates pagination parameters"""

    def __init__(self, max_limit: Optional[int] = None):
        """Initialize pagination validator.

        Args:
            max_limit: Maximum allowed limit value
        """
        self.max_limit = max_limit

    def validate(
        self,
        page: int = 1,
        skip: int = 0,
        limit: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> PaginationParams:
        """Validate and normalize pagination parameters.

        Args:
            page: Page number (1-indexed)
            skip: Number of records to skip
            limit: Maximum records per page
            order_by: Field to order by

        Returns:
            Validated pagination parameters

        Raises:
            HTTPException: If parameters are invalid
        """
        # Validate page
        if page < 1:
            raise HTTPException(422, "page must be >= 1")

        # Validate skip
        if skip < 0:
            raise HTTPException(422, "skip must be >= 0")

        # Validate limit
        if limit is not None:
            if limit <= 0:
                raise HTTPException(422, "limit must be > 0")
            if self.max_limit and limit > self.max_limit:
                raise HTTPException(422, f"limit must be <= {self.max_limit}")

        # Apply max_limit if both specified
        if limit and self.max_limit:
            limit = min(limit, self.max_limit)
        elif not limit and self.max_limit:
            limit = self.max_limit

        # Convert skip to page if needed
        if skip > 0 and limit:
            page = (skip // limit) + 1

        return {
            "page": page,
            "limit": limit,
            "skip": skip if skip > 0 else (page - 1) * limit if limit else 0,
            "order_by": order_by,
        }


class PaginationResult:
    """Builds pagination results"""

    @staticmethod
    def build(
        data: List[Any],
        total_count: int,
        page: int,
        limit: Optional[int],
    ) -> dict[str, Any]:
        """Build paginated response.

        Args:
            data: List of items for current page
            total_count: Total number of items
            page: Current page number
            limit: Items per page

        Returns:
            Dict with pagination metadata and data
        """
        return {
            "pagination": {
                "total_records": total_count,
                "total_pages": math.ceil(total_count / limit) if limit else 1,
                "current_page": page,
            },
            "data": data,
        }
