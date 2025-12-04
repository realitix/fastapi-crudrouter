"""Tests for filter generation and filtering functionality"""

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional, Union

from pydantic import BaseModel

from fastapi_crudrouter.schema_factory import (
    _is_enum_type,
    _is_string_like_type,
    extract_python_type,
    generate_fields_with_suffixes,
)

# Import Pydantic string types for testing
try:
    from pydantic import AnyUrl, EmailStr, HttpUrl

    PYDANTIC_TYPES_AVAILABLE = True
except ImportError:
    PYDANTIC_TYPES_AVAILABLE = False


class TestExtractPythonType:
    """Tests unitaires pour extract_python_type()"""

    def test_extract_from_optional_str(self):
        """Test extraction of str from Optional[str]"""
        result = extract_python_type(Optional[str])
        assert result is str

    def test_extract_from_union_str_none(self):
        """Test extraction of str from Union[str, None]"""
        result = extract_python_type(Union[str, None])
        assert result is str

    def test_extract_from_modern_union(self):
        """Test extraction of str from str | None syntax"""
        # Note: str | None creates UnionType in Python 3.10+
        result = extract_python_type(str | None)
        assert result is str

    def test_extract_from_optional_int(self):
        """Test extraction of int from Optional[int]"""
        result = extract_python_type(Optional[int])
        assert result is int

    def test_extract_from_optional_date(self):
        """Test extraction of date from Optional[date]"""
        result = extract_python_type(Optional[date])
        assert result is date

    def test_extract_from_optional_datetime(self):
        """Test extraction of datetime from Optional[datetime]"""
        result = extract_python_type(Optional[datetime])
        assert result is datetime

    def test_extract_from_simple_str(self):
        """Test that simple str type returns str"""
        result = extract_python_type(str)
        assert result is str

    def test_extract_from_simple_int(self):
        """Test that simple int type returns int"""
        result = extract_python_type(int)
        assert result is int

    def test_extract_from_annotated_str(self):
        """Test extraction of str from Annotated[str, metadata]"""
        result = extract_python_type(Annotated[str, "metadata"])
        assert result is str

    def test_extract_from_optional_annotated_str(self):
        """Test extraction from Optional[Annotated[str, metadata]]"""
        result = extract_python_type(Optional[Annotated[str, "metadata"]])
        assert result is str

    def test_extract_from_annotated_int(self):
        """Test extraction of int from Annotated[int, metadata]"""
        result = extract_python_type(Annotated[int, "metadata"])
        assert result is int

    def test_extract_from_optional_pydantic_httpurl(self):
        """Test extraction from Optional[HttpUrl] field annotation"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        # HttpUrl in a Pydantic model becomes Optional[Annotated[Url, ...]]
        class TestSchema(BaseModel):
            url: Optional[HttpUrl] = None

        field_type = TestSchema.model_fields["url"].annotation
        result = extract_python_type(field_type)

        # Should extract the actual Url type, not Annotated
        assert hasattr(result, "__name__")
        assert "Url" in result.__name__

    def test_extract_from_optional_pydantic_emailstr(self):
        """Test extraction from Optional[EmailStr] field annotation"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        class TestSchema(BaseModel):
            email: Optional[EmailStr] = None

        field_type = TestSchema.model_fields["email"].annotation
        result = extract_python_type(field_type)

        # Should extract EmailStr type
        assert result is EmailStr


class TestIsEnumType:
    """Tests unitaires pour _is_enum_type()"""

    def test_base_enum(self):
        """Test that Enum subclass returns True"""

        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        assert _is_enum_type(Status) is True

    def test_str_enum(self):
        """Test that str,Enum subclass returns True"""

        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        assert _is_enum_type(Status) is True

    def test_int_enum(self):
        """Test that IntEnum returns True"""
        from enum import IntEnum

        class Priority(IntEnum):
            LOW = 1
            MEDIUM = 2
            HIGH = 3

        assert _is_enum_type(Priority) is True

    def test_str_type_returns_false(self):
        """Test that str type returns False"""
        assert _is_enum_type(str) is False

    def test_int_type_returns_false(self):
        """Test that int type returns False"""
        assert _is_enum_type(int) is False

    def test_none_returns_false(self):
        """Test that None returns False"""
        assert _is_enum_type(None) is False

    def test_class_not_enum_returns_false(self):
        """Test that non-Enum class returns False"""

        class NotAnEnum:
            ACTIVE = "active"

        assert _is_enum_type(NotAnEnum) is False

    def test_enum_instance_returns_false(self):
        """Test that Enum instance (not type) returns False"""

        class Status(Enum):
            ACTIVE = "active"

        assert _is_enum_type(Status.ACTIVE) is False


class TestIsStringLikeType:
    """Tests unitaires pour _is_string_like_type()"""

    def test_base_str_type(self):
        """Test that base str type returns True"""
        assert _is_string_like_type(str) is True

    def test_int_type(self):
        """Test that int type returns False"""
        assert _is_string_like_type(int) is False

    def test_date_type(self):
        """Test that date type returns False"""
        assert _is_string_like_type(date) is False

    def test_datetime_type(self):
        """Test that datetime type returns False"""
        assert _is_string_like_type(datetime) is False

    def test_float_type(self):
        """Test that float type returns False"""
        assert _is_string_like_type(float) is False

    def test_bool_type(self):
        """Test that bool type returns False"""
        assert _is_string_like_type(bool) is False

    def test_emailstr_type(self):
        """Test that EmailStr type returns True"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        # EmailStr stays as EmailStr in field annotations
        class TestSchema(BaseModel):
            email: EmailStr

        field_type = extract_python_type(TestSchema.model_fields["email"].annotation)
        assert _is_string_like_type(field_type) is True

    def test_httpurl_type(self):
        """Test that HttpUrl type returns True"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        # HttpUrl becomes pydantic_core.Url in field annotations
        class TestSchema(BaseModel):
            url: HttpUrl

        field_type = extract_python_type(TestSchema.model_fields["url"].annotation)
        assert _is_string_like_type(field_type) is True

    def test_anyurl_type(self):
        """Test that AnyUrl type returns True"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        # AnyUrl becomes pydantic_core.Url in field annotations
        class TestSchema(BaseModel):
            url: AnyUrl

        field_type = extract_python_type(TestSchema.model_fields["url"].annotation)
        assert _is_string_like_type(field_type) is True

    def test_none_type(self):
        """Test that None type returns False"""
        assert _is_string_like_type(type(None)) is False

    def test_custom_class(self):
        """Test that custom class returns False"""

        class CustomClass:
            pass

        assert _is_string_like_type(CustomClass) is False

    def test_type_with_str_in_name(self):
        """Test that custom type with 'Str' in name returns True"""

        # Create a mock type with 'Str' in its name
        class CustomStr:
            __name__ = "CustomStr"

        assert _is_string_like_type(CustomStr) is True

    def test_type_with_email_in_name(self):
        """Test that custom type with 'Email' in name returns True"""

        class CustomEmail:
            __name__ = "CustomEmail"

        assert _is_string_like_type(CustomEmail) is True

    def test_type_with_url_in_name(self):
        """Test that custom type with 'Url' in name returns True"""

        class CustomUrl:
            __name__ = "CustomUrl"

        assert _is_string_like_type(CustomUrl) is True


class TestGenerateFieldsWithSuffixes:
    """Tests unitaires pour generate_fields_with_suffixes()"""

    def test_str_field_generates_like_suffix(self):
        """Test that string field generates __like suffix"""

        class TestSchema(BaseModel):
            name: str

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "name__like" in result
        assert result["name__like"] == (Optional[str], None)

    def test_optional_str_field_generates_like_suffix(self):
        """Test that Optional[str] field generates __like suffix"""

        class TestSchema(BaseModel):
            name: Optional[str] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "name__like" in result
        assert result["name__like"] == (Optional[str], None)

    def test_date_field_generates_range_suffixes(self):
        """Test that date field generates __gte and __lte suffixes"""

        class TestSchema(BaseModel):
            created_at: date

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "created_at__gte" in result
        assert "created_at__lte" in result
        assert result["created_at__gte"] == (Optional[date], None)
        assert result["created_at__lte"] == (Optional[date], None)

    def test_optional_date_field_generates_range_suffixes(self):
        """Test that Optional[date] field generates __gte and __lte suffixes"""

        class TestSchema(BaseModel):
            created_at: Optional[date] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "created_at__gte" in result
        assert "created_at__lte" in result

    def test_datetime_field_generates_range_suffixes(self):
        """Test that datetime field generates __gte and __lte suffixes"""

        class TestSchema(BaseModel):
            updated_at: datetime

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "updated_at__gte" in result
        assert "updated_at__lte" in result
        assert result["updated_at__gte"] == (Optional[datetime], None)
        assert result["updated_at__lte"] == (Optional[datetime], None)

    def test_int_field_no_suffix(self):
        """Test that int field does not generate suffixes"""

        class TestSchema(BaseModel):
            count: int

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "count__like" not in result
        assert "count__gte" not in result
        assert "count__lte" not in result

    def test_multiple_fields_generate_correct_suffixes(self):
        """Test multiple fields generate correct type-based suffixes"""

        class TestSchema(BaseModel):
            name: str
            description: Optional[str] = None
            count: int
            created_at: date

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # String fields should have __like
        assert "name__like" in result
        assert "description__like" in result

        # Int field should not have suffixes
        assert "count__like" not in result
        assert "count__gte" not in result

        # Date field should have __gte and __lte
        assert "created_at__gte" in result
        assert "created_at__lte" in result

    def test_no_duplicate_suffixes(self):
        """Test that existing suffix fields are not duplicated"""

        class TestSchema(BaseModel):
            name: str
            name__like: Optional[str] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # Should not add another name__like since it already exists
        matching_keys = [k for k in result if k.startswith("name__like")]
        assert len(matching_keys) == 0

    def test_field_with_double_underscore_generates_suffixes(self):
        """Test fields with __ generate proper suffixes"""

        class TestSchema(BaseModel):
            customer__id: str

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # Should generate __like suffix for string field even with __ in name
        assert "customer__id__like" in result
        assert result["customer__id__like"] == (Optional[str], None)

    def test_date_field_with_double_underscore_generates_range_suffixes(self):
        """Test that date fields containing __ generate range suffixes"""

        class TestSchema(BaseModel):
            created__at: date

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # Should generate __gte and __lte suffixes even with __ in name
        assert "created__at__gte" in result
        assert "created__at__lte" in result
        assert result["created__at__gte"] == (Optional[date], None)
        assert result["created__at__lte"] == (Optional[date], None)

    def test_operator_fields_are_not_processed(self):
        """Test existing operator fields are not processed"""

        class TestSchema(BaseModel):
            name: str
            name__like: Optional[str] = None
            created_at: date
            created_at__gte: Optional[date] = None
            created_at__lte: Optional[date] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # Should not generate duplicates for existing operator fields
        # name already has name__like, so should not add another
        assert "name__like" not in result
        # created_at already has both operators, so should not add them
        assert "created_at__gte" not in result
        assert "created_at__lte" not in result

    def test_emailstr_field_generates_like_suffix(self):
        """Test that EmailStr field generates __like suffix"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        class TestSchema(BaseModel):
            email: EmailStr

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "email__like" in result
        assert result["email__like"] == (Optional[str], None)

    def test_optional_emailstr_field_generates_like_suffix(self):
        """Test that Optional[EmailStr] field generates __like suffix"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        class TestSchema(BaseModel):
            email: Optional[EmailStr] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "email__like" in result
        assert result["email__like"] == (Optional[str], None)

    def test_httpurl_field_generates_like_suffix(self):
        """Test that HttpUrl field generates __like suffix"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        class TestSchema(BaseModel):
            website: HttpUrl

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "website__like" in result
        assert result["website__like"] == (Optional[str], None)

    def test_anyurl_field_generates_like_suffix(self):
        """Test that AnyUrl field generates __like suffix"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        class TestSchema(BaseModel):
            url: AnyUrl

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "url__like" in result
        assert result["url__like"] == (Optional[str], None)

    def test_mixed_str_and_emailstr_fields(self):
        """Test mixed str and EmailStr fields both generate __like"""
        if not PYDANTIC_TYPES_AVAILABLE:
            return

        class TestSchema(BaseModel):
            name: str
            email: EmailStr
            website: Optional[HttpUrl] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # All string-like fields should generate __like
        assert "name__like" in result
        assert "email__like" in result
        assert "website__like" in result

    def test_enum_field_generates_in_suffix(self):
        """Test that Enum field generates __in suffix"""

        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"
            PENDING = "pending"

        class TestSchema(BaseModel):
            status: Status

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "status__in" in result
        # Should be Optional[str] to accept comma-separated values from URL params
        assert result["status__in"] == (Optional[str], None)

    def test_optional_enum_field_generates_in_suffix(self):
        """Test that Optional[Enum] field generates __in suffix"""

        class Priority(str, Enum):
            LOW = "low"
            MEDIUM = "medium"
            HIGH = "high"

        class TestSchema(BaseModel):
            priority: Optional[Priority] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "priority__in" in result
        # Type should be Optional[str] to accept comma-separated values from URL params
        assert result["priority__in"] == (Optional[str], None)

    def test_int_enum_field_generates_in_suffix(self):
        """Test that IntEnum field generates __in suffix"""
        from enum import IntEnum

        class Level(IntEnum):
            LOW = 1
            MEDIUM = 2
            HIGH = 3

        class TestSchema(BaseModel):
            level: Level

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        assert "level__in" in result
        # Type should be Optional[str] to accept comma-separated values from URL params
        assert result["level__in"] == (Optional[str], None)

    def test_mixed_types_with_enum_generates_correct_suffixes(self):
        """Test mixed types including Enum generate correct suffixes"""

        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class TestSchema(BaseModel):
            name: str
            created_at: date
            status: Status
            count: int

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # String field should have __like
        assert "name__like" in result
        # Date field should have __gte and __lte
        assert "created_at__gte" in result
        assert "created_at__lte" in result
        # Enum field should have __in
        assert "status__in" in result
        # Int field should not have automatic suffixes
        assert "count__like" not in result
        assert "count__in" not in result

    def test_existing_in_field_not_duplicated(self):
        """Test that existing __in field is not duplicated"""

        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class TestSchema(BaseModel):
            status: Status
            status__in: Optional[list[Status]] = None

        base_fields = TestSchema.model_fields
        result = generate_fields_with_suffixes(base_fields)

        # Should not add another status__in since it already exists
        assert "status__in" not in result


class TestFilterIntegration:
    """Tests d'intégration pour le filtrage avec opérateurs spéciaux"""

    def test_like_filter_on_string_field(self, client):
        """Test that __like filter works on string fields"""
        # Clean database
        client.delete("/potato")

        # Create test data
        potatoes = [
            {
                "thickness": 0.1,
                "mass": 1.0,
                "color": "Brown Russet",
                "type": "TypeA",
            },
            {
                "thickness": 0.2,
                "mass": 1.5,
                "color": "Red",
                "type": "TypeB",
            },
            {
                "thickness": 0.3,
                "mass": 2.0,
                "color": "Brown Idaho",
                "type": "TypeC",
            },
        ]

        for potato in potatoes:
            res = client.post("/potato", json=potato)
            assert res.status_code == 201

        # Test filter with __like on color field
        res = client.get("/potato", params={"color__like": "Brown"})
        assert res.status_code == 200

        data = res.json()
        items = data["data"] if isinstance(data, dict) and "data" in data else data

        # Should return 2 potatoes with "Brown" in color
        assert len(items) == 2
        assert all("Brown" in item["color"] for item in items)

    def test_like_filter_case_insensitive(self, client):
        """Test that __like filter is case-insensitive"""
        # Clean database
        client.delete("/potato")

        # Create test data
        potato = {
            "thickness": 0.1,
            "mass": 1.0,
            "color": "BRIGHT RED",
            "type": "TypeA",
        }
        res = client.post("/potato", json=potato)
        assert res.status_code == 201

        # Test filter with lowercase search term
        res = client.get("/potato", params={"color__like": "bright"})
        assert res.status_code == 200

        data = res.json()
        items = data["data"] if isinstance(data, dict) and "data" in data else data

        # Should find the potato despite case difference
        assert len(items) == 1
        assert items[0]["color"] == "BRIGHT RED"
