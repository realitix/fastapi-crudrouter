from typing import Dict, Optional

import pytest

from .utils import compare_dict

basic_potato = {"thickness": 0.24, "mass": 1.2, "color": "Brown", "type": "Russet"}
URL = "/potato"


def extract_data_from_response(response_data):
    """Extract data from response, handling both old list format and new pagination format"""
    if isinstance(response_data, dict) and "data" in response_data:
        return response_data["data"]
    return response_data


def test_get(
    client, url: str = URL, params: Optional[dict] = None, expected_length: int = 0
):
    res = client.get(url, params=params)
    response_data = res.json()

    assert res.status_code == 200, response_data

    data = extract_data_from_response(response_data)
    assert isinstance(data, list) and len(data) == expected_length

    return data


def test_post(
    client, url: str = URL, model: Optional[Dict] = None, expected_length: int = 1
) -> dict:
    model = model or basic_potato
    res = client.post(url, json=model)
    assert res.status_code == 201, res.json()

    response_data = client.get(url).json()
    data = extract_data_from_response(response_data)
    assert len(data) == expected_length

    return res.json()


def test_get_one(
    client, url: str = URL, model: Optional[Dict] = None, id_key: str = "id"
):
    model = model or basic_potato
    res = client.post(url, json=model)
    assert res.status_code == 201
    id_ = res.json()[id_key]

    response_data = client.get(url).json()
    data = extract_data_from_response(response_data)
    assert len(data)

    res = client.get(f"{url}/{id_}")
    assert res.status_code == 200

    assert compare_dict(res.json(), model, exclude=[id_key])


def test_update(
    client, url: str = URL, model: Optional[Dict] = None, id_key: str = "id"
):
    """Test PUT - full update

    Note: This test verifies that PUT works correctly by sending all fields.
    The use of model.model_fields_set in _update() ensures that if a schema
    has optional fields (e.g., description: Optional[str] = None), omitting
    them in PUT won't overwrite the stored value with None. Since the test
    schemas don't have optional fields, we can't test that scenario here,
    but the implementation correctly handles it.
    """
    test_get(client, url, expected_length=0)

    model = model or basic_potato
    res = client.post(url, json=model)
    data = res.json()
    assert res.status_code == 201

    test_get(client, url, expected_length=1)

    tuber = dict(model.items())
    tuber["color"] = "yellow"

    res = client.put(f"{url}/{data[id_key]}", json=tuber)
    assert res.status_code == 200
    assert compare_dict(res.json(), tuber, exclude=[id_key])
    assert not compare_dict(res.json(), model, exclude=[id_key])

    res = client.get(f"{url}/{data[id_key]}")
    assert res.status_code == 200
    assert compare_dict(res.json(), tuber, exclude=[id_key])
    assert not compare_dict(res.json(), model, exclude=[id_key])


def test_patch(
    client, url: str = URL, model: Optional[Dict] = None, id_key: str = "id"
):
    """Test PATCH with partial payload - only provided fields should be updated"""
    test_get(client, url, expected_length=0)

    model = model or basic_potato
    res = client.post(url, json=model)
    data = res.json()
    assert res.status_code == 201

    test_get(client, url, expected_length=1)

    # PATCH with only one field
    partial_update = {"color": "yellow"}
    res = client.patch(f"{url}/{data[id_key]}", json=partial_update)
    assert res.status_code == 200, f"PATCH failed: {res.json()}"

    updated = res.json()
    # The color should be updated
    assert updated["color"] == "yellow"
    # All other fields should remain unchanged
    assert updated["thickness"] == model["thickness"]
    assert updated["mass"] == model["mass"]
    assert updated["type"] == model["type"]

    # Verify with GET
    res = client.get(f"{url}/{data[id_key]}")
    assert res.status_code == 200
    retrieved = res.json()
    assert retrieved["color"] == "yellow"
    assert retrieved["thickness"] == model["thickness"]
    assert retrieved["mass"] == model["mass"]
    assert retrieved["type"] == model["type"]

    # PATCH with multiple fields
    partial_update2 = {"thickness": 0.5, "mass": 2.0}
    res = client.patch(f"{url}/{data[id_key]}", json=partial_update2)
    assert res.status_code == 200

    updated2 = res.json()
    assert updated2["thickness"] == 0.5
    assert updated2["mass"] == 2.0
    assert updated2["color"] == "yellow"  # Should still be yellow from previous update
    assert updated2["type"] == model["type"]  # Should still be original value


def test_patch_null_validation(
    client, url: str = URL, model: Optional[Dict] = None, id_key: str = "id"
):
    """Test that PATCH rejects explicit null for non-nullable fields but allows omission"""
    test_get(client, url, expected_length=0)

    model = model or basic_potato
    res = client.post(url, json=model)
    data = res.json()
    assert res.status_code == 201

    # Test 1: Can omit a non-nullable field (should succeed)
    partial_update = {"color": "blue"}
    res = client.patch(f"{url}/{data[id_key]}", json=partial_update)
    assert res.status_code == 200
    updated = res.json()
    assert updated["color"] == "blue"
    assert updated["thickness"] == model["thickness"]  # Should be unchanged

    # Test 2: Cannot send explicit null for non-nullable field (should fail with 422)
    null_update = {"thickness": None}
    res = client.patch(f"{url}/{data[id_key]}", json=null_update)
    assert res.status_code == 422, (
        f"Expected 422 for null in non-nullable field, got {res.status_code}"
    )
    error = res.json()
    assert "thickness" in error.get("detail", "").lower(), (
        "Error should mention 'thickness'"
    )

    # Test 3: Verify the resource was not modified by the failed update
    res = client.get(f"{url}/{data[id_key]}")
    assert res.status_code == 200
    retrieved = res.json()
    assert (
        retrieved["thickness"] == model["thickness"]
    )  # Should still be original value


def test_delete_one(
    client, url: str = URL, model: Optional[Dict] = None, id_key: str = "id"
):
    model = model or basic_potato
    res = client.post(url, json=model)
    created_item = res.json()
    assert res.status_code == 201

    res = client.get(f"{url}/{created_item[id_key]}")
    assert res.status_code == 200
    assert compare_dict(res.json(), model, exclude=[id_key])

    response_data = client.get(url).json()
    data = extract_data_from_response(response_data)
    length_before = len(data)

    res = client.delete(f"{url}/{created_item[id_key]}")
    assert res.status_code == 204
    # No content in 204 response, so no assertion on res.json()

    res = client.get(url)
    assert res.status_code == 200
    response_data = res.json()
    data = extract_data_from_response(response_data)
    assert len(data) < length_before


def test_delete_all(
    client,
    url: str = URL,
    model: Optional[Dict] = None,
    model2: Optional[Dict] = None,
):
    model = model or basic_potato
    model2 = model2 or basic_potato

    res = client.post(url, json=model)
    assert res.status_code == 201

    res = client.post(url, json=model2)
    assert res.status_code == 201

    response_data = client.get(url).json()
    data = extract_data_from_response(response_data)
    assert len(data) >= 2

    res = client.delete(url)
    assert res.status_code == 200
    # Delete all should return pagination format with empty data
    delete_response = res.json()
    delete_data = extract_data_from_response(delete_response)
    assert len(delete_data) == 0

    response_data = client.get(url).json()
    data = extract_data_from_response(response_data)
    assert len(data) == 0


@pytest.mark.parametrize("id_", [-1, 0, 4, "14"])
def test_not_found(client, id_, url: str = URL, model: Optional[Dict] = None):
    url = f"{url}/{id_}"
    model = model or basic_potato
    assert client.get(url).status_code == 404
    assert client.put(url, json=model).status_code == 404
    assert client.delete(url).status_code == 404


def test_dne(client):
    res = client.get("/")
    assert res.status_code == 404

    res = client.get("/tomatoes")
    assert res.status_code == 404


def test_patch_schema_derives_from_update_schema():
    """Test that patch_schema is derived from update_schema, not from the full read schema.

    This is a critical security test. If patch_schema were derived from the full
    read schema, PATCH would allow modifying fields that were deliberately excluded
    from update_schema (e.g., sensitive fields like is_admin, created_at, etc.).
    """
    # pylint: disable=import-outside-toplevel
    from pydantic import BaseModel  # noqa: PLC0415
    from sqlalchemy import Boolean, Column, Integer, String  # noqa: PLC0415
    from sqlalchemy.ext.declarative import declarative_base  # noqa: PLC0415

    from fastapi_crudrouter import CRUDRouter  # noqa: PLC0415

    Base = declarative_base()  # pylint: disable=invalid-name

    # Create a model with a sensitive field
    class UserModel(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        email = Column(String)
        is_admin = Column(Boolean, default=False)  # Sensitive field

    # Full read schema (includes sensitive field)
    class UserRead(BaseModel):
        id: int
        name: str
        email: str
        is_admin: bool  # Visible in read

        class Config:
            from_attributes = True

    # Restricted update schema (excludes sensitive field)
    class UserUpdate(BaseModel):
        name: str
        email: str
        # is_admin is NOT here - users should not be able to promote themselves

    # Create a mock session generator (won't be used in this test)
    async def get_session():
        yield None

    # Create router with custom update_schema
    router = CRUDRouter(
        schema=UserRead,
        update_schema=UserUpdate,
        db_model=UserModel,
        db=get_session,
    )

    # Verify that patch_schema only has fields from update_schema, not from read schema
    patch_fields = set(router.patch_schema.model_fields.keys())
    update_fields = set(router.update_schema.model_fields.keys())
    read_fields = set(UserRead.model_fields.keys())

    # patch_schema should have same fields as update_schema (minus id)
    assert patch_fields == update_fields, (
        f"patch_schema fields ({patch_fields}) should match update_schema fields ({update_fields})"
    )

    # Critical: is_admin should NOT be in patch_schema
    assert "is_admin" not in patch_fields, (
        "SECURITY BUG: is_admin is in patch_schema but not in update_schema! "
        "This allows users to bypass security restrictions via PATCH."
    )

    # is_admin should be in read schema (for reference)
    assert "is_admin" in read_fields

    # id should not be in any of the write schemas
    assert "id" not in patch_fields
    assert "id" not in update_fields


def test_patch_preserves_validators():
    """Test that patch_schema preserves validators from update_schema.

    This is a critical security test. If validators were lost during patch_schema
    generation, PATCH would accept invalid data that was explicitly rejected by
    the developer's validators (e.g., invalid emails, blacklisted values, etc.).
    """
    # pylint: disable=import-outside-toplevel
    from pydantic import BaseModel, field_validator, model_validator  # noqa: PLC0415
    from pydantic_core import ValidationError  # noqa: PLC0415

    # Create a schema with field validator
    class DataUpdate(BaseModel):
        name: str
        email: str

        @field_validator("email")
        @classmethod
        def validate_email(cls, v):
            if v and not v.endswith("@company.com"):
                raise ValueError("Only company emails allowed")
            return v  # Must return the value

        @model_validator(mode="after")
        @classmethod
        def check_not_blacklisted(cls, model):
            if model.name and model.name.lower() in ["admin", "root", "system"]:
                raise ValueError("Name is blacklisted")
            return model

    from fastapi_crudrouter.crud_router import (  # noqa: PLC0415
        optional_schema_factory,
    )

    # Generate patch schema
    patch_schema = optional_schema_factory(DataUpdate, pk_field_name="id", name="Patch")

    # Test 1: Valid data should pass
    valid_data = {"name": "John", "email": "john@company.com"}
    instance = patch_schema(**valid_data)
    assert instance.name == "John"
    assert instance.email == "john@company.com"

    # Test 2: Invalid email should be rejected by field_validator
    invalid_email = {"email": "hacker@evil.com"}
    try:
        patch_schema(**invalid_email)
        raise AssertionError("Should have raised ValidationError for invalid email")
    except ValidationError as e:
        assert "company emails" in str(e).lower() or "email" in str(e).lower()

    # Test 3: Blacklisted name should be rejected by model_validator
    blacklisted_name = {"name": "admin", "email": "admin@company.com"}
    try:
        patch_schema(**blacklisted_name)
        raise AssertionError("Should have raised ValidationError for blacklisted name")
    except ValidationError as e:
        assert "blacklisted" in str(e).lower() or "admin" in str(e).lower()

    # Test 4: Partial data (PATCH behavior) with valid email should pass
    partial_valid = {"email": "alice@company.com"}
    instance = patch_schema(**partial_valid)
    assert instance.email == "alice@company.com"
    assert instance.name is None  # Not provided, should be None (optional)

    # Test 5: Partial data with invalid email should still be rejected
    partial_invalid = {"email": "attacker@evil.com"}
    try:
        patch_schema(**partial_invalid)
        raise AssertionError(
            "Should have raised ValidationError for invalid email in partial update"
        )
    except ValidationError as e:
        assert "company emails" in str(e).lower() or "email" in str(e).lower()


def test_patch_preserves_field_aliases():
    """Test that patch_schema preserves field aliases from update_schema.

    This is a critical regression test. If aliases were lost during patch_schema
    generation, PATCH would break for any project using field aliases for API
    compatibility (e.g., camelCase to snake_case conversion).
    """
    # pylint: disable=import-outside-toplevel
    from pydantic import BaseModel, Field  # noqa: PLC0415
    from pydantic_core import ValidationError  # noqa: PLC0415

    # Create a schema with field aliases (common for API compatibility)
    class UserUpdate(BaseModel):
        full_name: str = Field(alias="fullName")
        email_address: str = Field(alias="emailAddress", min_length=5)

    from fastapi_crudrouter.crud_router import (  # noqa: PLC0415
        optional_schema_factory,
    )

    # Generate patch schema
    patch_schema = optional_schema_factory(UserUpdate, pk_field_name="id", name="Patch")

    # Test 1: Alias should work (using camelCase API names)
    data_with_alias = {"fullName": "Alice Smith", "emailAddress": "alice@company.com"}
    instance = patch_schema(**data_with_alias)
    assert instance.full_name == "Alice Smith"
    assert instance.email_address == "alice@company.com"

    # Test 2: Partial update with alias (PATCH behavior)
    partial_with_alias = {"emailAddress": "charlie@company.com"}
    instance2 = patch_schema(**partial_with_alias)
    assert instance2.email_address == "charlie@company.com"
    assert instance2.full_name is None  # Not provided, should be None

    # Test 3: Partial update with just one alias
    partial_name = {"fullName": "Diana Prince"}
    instance3 = patch_schema(**partial_name)
    assert instance3.full_name == "Diana Prince"
    assert instance3.email_address is None

    # Test 4: Field constraints should also be preserved (min_length)
    invalid_email = {"emailAddress": "ab"}  # Too short
    try:
        patch_schema(**invalid_email)
        raise AssertionError(
            "Should have raised ValidationError for min_length constraint"
        )
    except ValidationError as e:
        assert (
            "at least 5 characters" in str(e).lower()
            or "min_length" in str(e).lower()
            or "emailaddress" in str(e).lower()
        )

    # Test 5: Verify aliases are actually in the model fields
    assert patch_schema.model_fields["full_name"].alias == "fullName"
    assert patch_schema.model_fields["email_address"].alias == "emailAddress"


def test_patch_null_check_uses_update_schema():
    """Test that PATCH null validation uses update_schema, not read schema.

    This is a critical security test. If null validation checked the read schema
    instead of the update schema, attackers could bypass required-field constraints
    by exploiting differences between read and write schemas.
    """
    # pylint: disable=import-outside-toplevel
    from pydantic import BaseModel  # noqa: PLC0415
    from sqlalchemy import Column, Integer, String  # noqa: PLC0415
    from sqlalchemy.ext.declarative import declarative_base  # noqa: PLC0415

    from fastapi_crudrouter import CRUDRouter  # noqa: PLC0415

    Base = declarative_base()  # pylint: disable=invalid-name

    # Scenario 1: Field required in update but absent from read schema
    # (e.g., password field not visible in read but required for update)

    class UserModel(Base):
        __tablename__ = "users_scenario1"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        password = Column(String, nullable=False)

    # Read schema: password field is NOT included (hidden from API responses)
    class UserRead(BaseModel):
        id: int
        name: str

        class Config:
            from_attributes = True

    # Update schema: password is required (non-optional)
    class UserUpdate(BaseModel):
        name: str
        password: str  # Required, must not be null

    async def get_session():
        yield None

    router = CRUDRouter(
        schema=UserRead,
        update_schema=UserUpdate,
        db_model=UserModel,
        db=get_session,
    )

    # Critical test: password is NOT in read schema, but IS in update schema
    # The null guard must check update_schema, not read schema
    # If it checks read schema, password won't be found and null will be allowed

    # Verify that patch_schema correctly derives from update_schema
    patch_fields = set(router.patch_schema.model_fields.keys())
    update_fields = set(router.update_schema.model_fields.keys())
    read_fields = set(UserRead.model_fields.keys())

    # patch_schema should have same fields as update_schema
    assert patch_fields == update_fields
    # password should be in patch_schema even though not in read schema
    assert "password" in patch_fields
    assert "password" not in read_fields

    # Verify that password in patch_schema is Optional (for partial updates)
    # but the null guard should still reject explicit null based on update_schema
    # pylint: disable=import-outside-toplevel
    from fastapi_crudrouter.schema_factory import is_optional_type  # noqa: PLC0415

    password_annotation = router.patch_schema.model_fields["password"].annotation
    assert is_optional_type(password_annotation)  # Should be Optional for PATCH


def test_patch_null_check_required_field_different_optionality():
    """Test PATCH null validation when field has different optionality in read vs update.

    Scenario: Field is Optional in read schema but required in update schema.
    The null guard must respect the update schema's requirement.
    """
    # pylint: disable=import-outside-toplevel
    from pydantic import BaseModel  # noqa: PLC0415
    from sqlalchemy import Column, Integer, String  # noqa: PLC0415
    from sqlalchemy.ext.declarative import declarative_base  # noqa: PLC0415

    from fastapi_crudrouter import CRUDRouter  # noqa: PLC0415

    Base = declarative_base()  # pylint: disable=invalid-name

    class AccountModel(Base):
        __tablename__ = "accounts"
        id = Column(Integer, primary_key=True)
        name = Column(String)
        email = Column(String, nullable=False)

    # Read schema: email is Optional (may be hidden from some users)
    class AccountRead(BaseModel):
        id: int
        name: str
        email: str | None  # Optional in read

        class Config:
            from_attributes = True

    # Update schema: email is required (must not be null when updating)
    class AccountUpdate(BaseModel):
        name: str
        email: str  # Required in write!

    async def get_session():
        yield None

    CRUDRouter(
        schema=AccountRead,
        update_schema=AccountUpdate,
        db_model=AccountModel,
        db=get_session,
    )

    # Verify schemas have different optionality for email
    # pylint: disable=import-outside-toplevel,unsubscriptable-object
    from fastapi_crudrouter.schema_factory import is_optional_type  # noqa: PLC0415

    read_email_field = AccountRead.model_fields["email"]
    update_email_field = AccountUpdate.model_fields["email"]

    # Email is optional in read schema
    assert is_optional_type(read_email_field.annotation)
    # Email is required (non-optional) in update schema
    assert not is_optional_type(update_email_field.annotation)

    # The critical test: patch_schema should be derived from update_schema
    # So even though read schema allows null, patch should respect update schema
