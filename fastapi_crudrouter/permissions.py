"""Permission and access control utilities"""

from typing import Any, Callable, Optional

from fastapi import HTTPException


class PermissionChecker:
    """Handles permission checking for CRUD operations"""

    def __init__(
        self,
        permission_checker: Optional[Callable[[Any, str], bool]] = None,
        permissions: Optional[dict[str, Any]] = None,
    ):
        """Initialize permission checker.

        Args:
            permission_checker: Function that checks if user has permission
            permissions: Dict mapping operation names to required permissions
        """
        self.permission_checker = permission_checker
        self.permissions = permissions or {}

    def check(self, user: Any, operation: str) -> None:
        """Check if user has permission for operation.

        Args:
            user: Current user object
            operation: Operation name (e.g., "get_all", "create")

        Raises:
            HTTPException: 403 if user lacks permission
        """
        if not self.permission_checker:
            return  # No permission checking configured

        if operation not in self.permissions:
            return  # No permission required for this operation

        if not user:
            raise HTTPException(401, "Authentication required")

        required_permission = self.permissions[operation]
        has_permission = self.permission_checker(user, required_permission)

        if not has_permission:
            raise HTTPException(
                403,
                f"Permission denied: requires {required_permission}",
            )


class AccessChecker:
    """Handles resource-level access checking"""

    def __init__(
        self,
        access_checker: Optional[Callable] = None,
    ):
        """Initialize access checker.

        Args:
            access_checker: Async function that checks resource access
        """
        self.access_checker = access_checker

    async def check(
        self,
        item_id: Any,
        user: Any,
        db: Any,
    ) -> None:
        """Check if user can access specific resource.

        Args:
            item_id: Resource identifier
            user: Current user object
            db: Database session

        Raises:
            HTTPException: If access denied
        """
        if not self.access_checker:
            return  # No access checking configured

        if not user:
            raise HTTPException(401, "Authentication required")

        await self.access_checker(item_id, user, db)
