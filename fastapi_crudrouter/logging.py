"""Structured logging for CRUD operations"""

import logging
from typing import Any, Optional

logger = logging.getLogger("fastapi_crudrouter")


class CRUDLogger:
    """Structured logger for CRUD operations"""

    def __init__(self, model_name: str):
        """Initialize CRUD logger.

        Args:
            model_name: Name of the model being operated on
        """
        self.model_name = model_name
        self.logger = logger

    def log_operation(  # pylint: disable=too-many-positional-arguments
        self,
        operation: str,
        item_id: Optional[Any] = None,
        user_id: Optional[Any] = None,
        filters: Optional[dict] = None,
        success: bool = True,
        error: Optional[Exception] = None,
    ) -> None:
        """Log a CRUD operation.

        Args:
            operation: Operation name (create, read, update, delete)
            item_id: Resource ID (if applicable)
            user_id: User performing operation
            filters: Filters applied (for list operations)
            success: Whether operation succeeded
            error: Exception if operation failed
        """
        log_data = {
            "model": self.model_name,
            "operation": operation,
            "success": success,
        }

        if item_id is not None:
            log_data["item_id"] = item_id
        if user_id is not None:
            log_data["user_id"] = user_id
        if filters:
            log_data["filters"] = filters
        if error:
            log_data["error"] = str(error)

        level = logging.INFO if success else logging.ERROR
        self.logger.log(level, "CRUD %s", operation, extra=log_data)
