# Advanced Usage Guide

## Table of Contents
1. [Custom Schemas](#custom-schemas)
2. [Filtering](#filtering)
3. [Pagination](#pagination)
4. [Joins and Relationships](#joins-and-relationships)
5. [Permissions and Access Control](#permissions-and-access-control)
6. [Custom Validators](#custom-validators)
7. [Overriding Routes](#overriding-routes)

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

## Custom Validators

### Create Validator
```python
async def validate_user_create(
    data: UserCreate,
    user: User,
    db: AsyncSession
) -> UserCreate:
    # Check if email already exists
    existing = await db.execute(
        select(User).where(User.email == data.email)
    )
    if existing.first():
        raise HTTPException(422, "Email already exists")

    # Add creator ID
    data.created_by = user.id
    return data

router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    create_validator=validate_user_create
)
```

### Update Validator
```python
async def validate_user_update(
    item_id: int,      # ID of the resource being updated
    data: UserUpdate,
    user: User,
    db: AsyncSession
) -> UserUpdate:
    # Fetch existing resource to check its state
    existing = await db.get(User, item_id)
    if not existing:
        raise HTTPException(404, "User not found")

    # Prevent non-admin from promoting users
    if hasattr(data, "role") and data.role == "admin":
        if not user.is_admin:
            raise HTTPException(403, "Cannot promote to admin")

    # Prevent updating locked resources
    if existing.is_locked and not user.is_admin:
        raise HTTPException(400, "Cannot update locked user")

    return data

router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    update_validator=validate_user_update
)
```

## Overriding Routes

### Override Single Route
```python
router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session
)

@router.get("/{item_id}")
async def custom_get_one(item_id: int):
    # Custom implementation
    return {"custom": True, "id": item_id}
```

### Disable Specific Routes
```python
router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    delete_all_route=False,  # Disable dangerous delete all
    get_all_options_route=False  # Disable OPTIONS
)
```

### Add Custom Dependencies to Routes
```python
from fastapi import Depends

def require_admin(user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(403)

router = CRUDRouter(
    schema=UserSchema,
    db_model=User,
    db=get_session,
    delete_one_route=[Depends(require_admin)],  # Only admin can delete
)
```
