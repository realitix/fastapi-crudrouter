# Advanced Usage Guide

## Table of Contents

1. [Custom Schemas](#custom-schemas)
2. [Filtering](#filtering)
3. [Pagination](#pagination)
4. [Joins and Relationships](#joins-and-relationships)
5. [Permissions and Access Control](#permissions-and-access-control)
6. [Validators](#validators)
7. [Lifecycle Hooks](#lifecycle-hooks)
8. [Soft Delete](#soft-delete)
9. [Bulk Operations](#bulk-operations)
10. [Overriding Routes](#overriding-routes)
11. [Quick Reference](#quick-reference)

---

## Custom Schemas

### Create Schema
By default, create schema excludes the primary key. Customize it:

```python
from pydantic import BaseModel, Field

class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    age: int = Field(..., ge=18, le=120)

router = CRUDRouter(
    schema=User,
    db_model=UserModel,
    db=get_session,
    create_schema=UserCreate
)
```

### Update Schema
Separate schema for updates (PUT requests):

```python
class UserUpdate(BaseModel):
    name: str
    email: EmailStr
    # age is not updatable

router = CRUDRouter(
    schema=User,
    db_model=UserModel,
    db=get_session,
    update_schema=UserUpdate
)
```

### Patch Schema
For partial updates (PATCH), all fields are optional by default.
Customize if needed:

```python
class UserPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None

router = CRUDRouter(
    schema=User,
    db_model=UserModel,
    db=get_session,
    patch_schema=UserPatch
)
```

## Filtering

### Basic Filtering
```python
# GET /users?name=John&age=30
# Returns users where name="John" AND age=30
```

### Filter Operators

#### String Fields: __like
```python
# GET /users?name__like=John
# Returns users where name contains "John" (case-insensitive)
```

#### Date/Datetime Fields: __gte, __lte
```python
# GET /users?created_at__gte=2024-01-01&created_at__lte=2024-12-31
# Returns users created in 2024
```

#### List Fields: __in
```python
# GET /users?status__in=active&status__in=pending
# Returns users with status "active" OR "pending"
```

### Custom Filter Schema

```python
from typing import Annotated
from sqlalchemy.orm import relationship

class UserFilter(BaseModel):
    name: Optional[str] = None
    age_min: Optional[int] = Field(None, alias="age__gte")
    age_max: Optional[int] = Field(None, alias="age__lte")

    # Filter by related model
    department: Optional[str] = Field(
        None,
        metadata=[Department.name]  # Join on Department.name
    )

    # Custom filter function
    active_only: Optional[bool] = Field(
        None,
        metadata=[
            lambda query, value: query.where(User.status == "active") if value else query
        ]
    )

router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    filter_schema=UserFilter
)
```

## Pagination

### Basic Pagination
```python
# GET /users?page=2&limit=20
# Returns page 2 with 20 items per page

# Response:
{
    "pagination": {
        "total_records": 100,
        "total_pages": 5,
        "current_page": 2
    },
    "data": [...]
}
```

### Skip-based Pagination
```python
# GET /users?skip=40&limit=20
# Skip first 40, return next 20
```

### Maximum Limit
```python
router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    paginate=100  # Maximum 100 items per page
)
```

### Ordering
```python
# GET /users?order_by=name
# Order by name ASC

# GET /users?order_by=created_at__DESC
# Order by created_at DESC
```

## Joins and Relationships

### Single Relationship (One-to-One, Many-to-One)
```python
from typing import Annotated
from pydantic import Field

class DepartmentSchema(BaseModel):
    id: int
    name: str

class UserSchema(BaseModel):
    id: int
    name: str
    # Include department in response
    department: Annotated[
        DepartmentSchema,
        Field(metadata=[User.department])  # User.department is relationship
    ]

# GET /users/1
# Response:
{
    "id": 1,
    "name": "John",
    "department": {"id": 5, "name": "Engineering"}
}
```

### List Relationship (One-to-Many)
```python
class PostSchema(BaseModel):
    id: int
    title: str

class UserSchema(BaseModel):
    id: int
    name: str
    # Include all user's posts
    posts: Annotated[
        List[PostSchema],
        Field(metadata=[(Post, Post.user_id, PostSchema)])
    ]

# GET /users/1
# Response:
{
    "id": 1,
    "name": "John",
    "posts": [
        {"id": 1, "title": "First Post"},
        {"id": 2, "title": "Second Post"}
    ]
}
```

### Custom Query Functions
```python
def only_published(query):
    return query.where(Post.published == True)

class UserSchema(BaseModel):
    id: int
    posts_published: Annotated[
        List[PostSchema],
        Field(metadata=[only_published])
    ]
```

## Permissions and Access Control

### Permission Checker
```python
from fastapi import Depends
from typing import Any

def get_current_user(token: str = Header(...)):
    # Verify token and return user
    return User(...)

def check_permission(user: User, required_permission: str) -> bool:
    return required_permission in user.permissions

router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    current_user_dependency=get_current_user,
    permission_checker=check_permission,
    permissions={
        "get_all": "users:read",
        "get_one": "users:read",
        "create": "users:write",
        "update": "users:write",
        "delete_one": "users:delete",
    }
)
```

### Access Checker (Resource-level)
```python
async def check_user_access(
    item_id: int,
    user: User,
    db: AsyncSession
):
    """Check if user can access specific resource"""
    resource = await db.get(User, item_id)
    if not resource:
        raise HTTPException(404)

    if resource.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Not authorized to access this resource")

router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    access_checker=check_user_access
)
```

### Contextual Filtering
```python
def get_user_context(user: User = Depends(get_current_user)):
    """Add implicit filters based on user context"""
    if user.is_admin:
        return {}  # Admin sees everything
    return {"owner_id": user.id}  # Users only see their own

router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    contextual_filter=get_user_context
)

# GET /resources
# Non-admin users automatically filtered to their own resources
```

## Validators

### Create Validator
```python
async def validate_create(data: ItemCreate, user: User, db: AsyncSession) -> ItemCreate:
    existing = await db.execute(select(Item).where(Item.name == data.name))
    if existing.first():
        raise HTTPException(422, "Name already exists")
    return data

router = CRUDRouter(..., create_validator=validate_create)
```

### Update Validator
```python
async def validate_update(item_id: int, data: ItemUpdate, user: User, db: AsyncSession) -> ItemUpdate:
    existing = await db.get(Item, item_id)
    if existing.is_locked and not user.is_admin:
        raise HTTPException(400, "Cannot update locked item")
    return data

router = CRUDRouter(..., update_validator=validate_update)
```

### Delete Validator
```python
async def validate_delete(item_id: int, user: User, db: AsyncSession) -> None:
    item = await db.get(Item, item_id)
    if item.is_default:
        raise HTTPException(400, "Cannot delete default item")
    if item.has_children:
        raise HTTPException(400, "Cannot delete item with children")

router = CRUDRouter(..., delete_validator=validate_delete)
```

### Create Defaults
Auto-fill fields from user context on create:
```python
def get_defaults(user: User) -> dict:
    return {"school_id": user.school_id, "created_by_id": user.id}

router = CRUDRouter(..., create_defaults=get_defaults)
# POST /items {"name": "Doc"} -> {"name": "Doc", "school_id": 123, "created_by_id": 42}
```
- Defaults applied before `create_validator`
- Explicit request values override defaults

## Lifecycle Hooks

Execute side effects after CRUD operations.

### Hook Signatures
```python
# after_create/after_update: receive model instance
async def on_create(model: Model, user: User, db: AsyncSession) -> None: ...

# after_delete: receives item_id (model already deleted)
async def on_delete(item_id: int, user: User, db: AsyncSession) -> None: ...
```

### Usage
```python
async def recalc_average(score: Score, user: User, db: AsyncSession) -> None:
    await recalculate_student_average(score.student_id, db)

async def cleanup(item_id: int, user: User, db: AsyncSession) -> None:
    await cleanup_orphaned_files(item_id, db)

router = CRUDRouter(
    ...,
    after_create=recalc_average,
    after_update=recalc_average,
    after_delete=cleanup,
)
```
- Hooks run after successful DB commit
- Hook errors are logged but don't rollback main operation

---

## Soft Delete

Mark records as deleted instead of removing them.

### Configuration
```python
router = CRUDRouter(
    ...,
    soft_delete=True,
    soft_delete_field="is_deleted",       # Field to mark (default)
    soft_delete_value=True,               # Value when deleted (default)
    soft_delete_timestamp_field="deleted_at",  # Optional timestamp
    soft_delete_by_field="deleted_by_id",      # Optional user tracking
)
```

### Behavior
- `DELETE /{id}` sets field instead of removing row
- `GET /` and `GET /{id}` auto-filter soft-deleted items
- `GET /?include_deleted=true` shows all items

---

## Bulk Operations

Enable bulk endpoints for efficient batch processing.

### Configuration
```python
router = CRUDRouter(
    ...,
    bulk_create_route=True,
    bulk_update_route=True,
    bulk_delete_route=True,
    bulk_max_items=100,          # Max items per request
    bulk_partial_success=True,   # Continue on individual failures
)
```

### Bulk Create: `POST /bulk`
```python
# Request: List of items
[{"name": "Item 1"}, {"name": "Item 2"}]

# Response
{
    "created": [{"index": 0, "id": 1, "data": {...}}, ...],
    "errors": [],
    "success_count": 2,
    "error_count": 0
}
```

### Bulk Update: `PATCH /bulk`
```python
# Request: List with pk field
[{"id": 1, "name": "Updated"}, {"id": 2, "status": "active"}]

# Response
{
    "updated": [{"index": 0, "id": 1, "updated_fields": ["name"]}, ...],
    "errors": [],
    "success_count": 2,
    "error_count": 0
}
```

### Bulk Delete: `DELETE /bulk`
```python
# Request: List of IDs
[1, 2, 3]

# Response
{
    "deleted_ids": [1, 2, 3],
    "errors": [],
    "success_count": 3,
    "error_count": 0
}
```

### Partial Success
With `bulk_partial_success=True`, failed items are reported but don't stop the batch:
```python
{"success_count": 2, "error_count": 1, "errors": [{"index": 1, "error": "..."}]}
```
With `bulk_partial_success=False`, entire batch fails atomically.

---

## Overriding Routes

### Override Single Route
```python
router = CRUDRouter(schema=UserSchema, db_model=User, db=get_session)

@router.get("/{item_id}")
async def custom_get_one(item_id: int):
    return {"custom": True, "id": item_id}
```

### Disable Routes
```python
router = CRUDRouter(..., delete_all_route=False, get_all_options_route=False)
```

### Add Dependencies
```python
def require_admin(user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(403)

router = CRUDRouter(..., delete_one_route=[Depends(require_admin)])
```

---

## Quick Reference

### All Parameters
```python
CRUDRouter(
    # Required
    schema: Type[BaseModel],
    db_model: ModelType,
    db: SessionGenerator,

    # Schemas
    create_schema: Optional[Type[BaseModel]] = None,
    update_schema: Optional[Type[BaseModel]] = None,
    patch_schema: Optional[Type[BaseModel]] = None,
    get_all_schema: Optional[Type[BaseModel]] = None,
    filter_schema: Optional[Type[BaseModel]] = None,

    # Routing
    prefix: Optional[str] = None,
    tags: Optional[List[str]] = None,
    paginate: Optional[int] = None,
    default_order_by: Optional[str] = None,  # e.g., "created_at__DESC"

    # Route control (bool or List[Depends])
    get_all_route: Union[bool, List[Depends]] = True,
    get_all_options_route: Union[bool, List[Depends]] = True,
    get_one_route: Union[bool, List[Depends]] = True,
    create_route: Union[bool, List[Depends]] = True,
    update_route: Union[bool, List[Depends]] = True,
    delete_one_route: Union[bool, List[Depends]] = True,
    delete_all_route: Union[bool, List[Depends]] = True,

    # Security
    current_user_dependency: Optional[Callable] = None,
    contextual_filter: Optional[Callable] = None,
    access_checker: Optional[Callable] = None,
    permission_checker: Optional[Callable] = None,
    permissions: Optional[dict] = None,

    # Validators
    create_validator: Optional[Callable] = None,
    update_validator: Optional[Callable] = None,
    delete_validator: Optional[Callable] = None,
    create_defaults: Optional[Callable] = None,

    # Lifecycle hooks
    after_create: Optional[Callable] = None,
    after_update: Optional[Callable] = None,
    after_delete: Optional[Callable] = None,

    # Soft delete
    soft_delete: bool = False,
    soft_delete_field: str = "is_deleted",
    soft_delete_value: Any = True,
    soft_delete_timestamp_field: Optional[str] = None,
    soft_delete_by_field: Optional[str] = None,

    # Bulk operations
    bulk_create_route: Union[bool, List[Depends]] = False,
    bulk_update_route: Union[bool, List[Depends]] = False,
    bulk_delete_route: Union[bool, List[Depends]] = False,
    bulk_max_items: int = 100,
    bulk_partial_success: bool = True,
)
```
