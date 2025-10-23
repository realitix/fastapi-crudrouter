"""Tests for filter generation and filtering functionality"""

from datetime import date, datetime
from typing import Optional, Union

from pydantic import BaseModel

from fastapi_crudrouter.crud_router import (
    extract_python_type,
    generate_fields_with_suffixes,
)


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
        if isinstance(data, dict) and "data" in data:
            items = data["data"]
        else:
            items = data

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
        if isinstance(data, dict) and "data" in data:
            items = data["data"]
        else:
            items = data

        # Should find the potato despite case difference
        assert len(items) == 1
        assert items[0]["color"] == "BRIGHT RED"
