"""Unit tests for pagination module"""

from fastapi import HTTPException
import pytest

from fastapi_crudrouter.pagination import (
    PaginationParams,
    PaginationResult,
    PaginationValidator,
)


class TestPaginationValidator:
    """Test PaginationValidator class"""

    def test_init_without_max_limit(self):
        """Test initialization without max_limit"""
        validator = PaginationValidator()
        assert validator.max_limit is None

    def test_init_with_max_limit(self):
        """Test initialization with max_limit"""
        validator = PaginationValidator(max_limit=100)
        assert validator.max_limit == 100

    def test_validate_default_values(self):
        """Test validation with default values"""
        validator = PaginationValidator()
        result = validator.validate()
        assert result["page"] == 1
        assert result["skip"] == 0
        assert result["limit"] is None
        assert result["order_by"] is None

    def test_validate_custom_page(self):
        """Test validation with custom page"""
        validator = PaginationValidator()
        result = validator.validate(page=5, limit=10)
        assert result["page"] == 5
        assert result["skip"] == 40  # (5-1) * 10

    def test_validate_custom_limit(self):
        """Test validation with custom limit"""
        validator = PaginationValidator()
        result = validator.validate(page=1, limit=50)
        assert result["limit"] == 50

    def test_validate_skip_parameter(self):
        """Test validation with skip parameter"""
        validator = PaginationValidator()
        result = validator.validate(skip=20, limit=10)
        assert result["page"] == 3  # (20 // 10) + 1
        assert result["skip"] == 20

    def test_validate_order_by(self):
        """Test validation with order_by parameter"""
        validator = PaginationValidator()
        result = validator.validate(order_by="name__DESC")
        assert result["order_by"] == "name__DESC"

    def test_validate_page_less_than_1_raises_error(self):
        """Test that page < 1 raises HTTPException"""
        validator = PaginationValidator()
        with pytest.raises(HTTPException) as exc_info:
            validator.validate(page=0)
        assert exc_info.value.status_code == 422
        assert "page must be >= 1" in str(exc_info.value.detail)

    def test_validate_negative_page_raises_error(self):
        """Test that negative page raises HTTPException"""
        validator = PaginationValidator()
        with pytest.raises(HTTPException) as exc_info:
            validator.validate(page=-1)
        assert exc_info.value.status_code == 422

    def test_validate_negative_skip_raises_error(self):
        """Test that skip < 0 raises HTTPException"""
        validator = PaginationValidator()
        with pytest.raises(HTTPException) as exc_info:
            validator.validate(skip=-1)
        assert exc_info.value.status_code == 422
        assert "skip must be >= 0" in str(exc_info.value.detail)

    def test_validate_zero_limit_raises_error(self):
        """Test that limit <= 0 raises HTTPException"""
        validator = PaginationValidator()
        with pytest.raises(HTTPException) as exc_info:
            validator.validate(limit=0)
        assert exc_info.value.status_code == 422
        assert "limit must be > 0" in str(exc_info.value.detail)

    def test_validate_negative_limit_raises_error(self):
        """Test that negative limit raises HTTPException"""
        validator = PaginationValidator()
        with pytest.raises(HTTPException) as exc_info:
            validator.validate(limit=-10)
        assert exc_info.value.status_code == 422

    def test_validate_limit_exceeds_max_limit_raises_error(self):
        """Test that limit > max_limit raises HTTPException"""
        validator = PaginationValidator(max_limit=100)
        with pytest.raises(HTTPException) as exc_info:
            validator.validate(limit=200)
        assert exc_info.value.status_code == 422
        assert "limit must be <= 100" in str(exc_info.value.detail)

    def test_validate_limit_equals_max_limit(self):
        """Test that limit == max_limit is accepted"""
        validator = PaginationValidator(max_limit=100)
        result = validator.validate(limit=100)
        assert result["limit"] == 100

    def test_validate_applies_max_limit_when_both_specified(self):
        """Test that limit exceeding max_limit raises error"""
        validator = PaginationValidator(max_limit=50)
        # Should raise error when limit > max_limit
        with pytest.raises(HTTPException) as exc_info:
            validator.validate(limit=100)
        assert exc_info.value.status_code == 422

    def test_validate_uses_max_limit_when_limit_not_provided(self):
        """Test that max_limit is used when limit is not provided"""
        validator = PaginationValidator(max_limit=50)
        result = validator.validate()
        assert result["limit"] == 50

    def test_validate_combines_limit_and_max_limit(self):
        """Test that limit is capped by max_limit"""
        validator = PaginationValidator(max_limit=50)
        result = validator.validate(limit=30)
        assert result["limit"] == 30

    def test_validate_skip_with_no_limit(self):
        """Test validation with skip but no limit"""
        validator = PaginationValidator()
        result = validator.validate(skip=20)
        # When skip is provided but no limit, skip conversion shouldn't happen
        assert result["skip"] == 20

    def test_validate_complex_scenario(self):
        """Test complex scenario with all parameters"""
        validator = PaginationValidator(max_limit=100)
        result = validator.validate(
            page=3, skip=0, limit=25, order_by="created_at__DESC"
        )
        assert result["page"] == 3
        assert result["limit"] == 25
        assert result["skip"] == 50  # (3-1) * 25
        assert result["order_by"] == "created_at__DESC"


class TestPaginationResult:
    """Test PaginationResult class"""

    def test_build_with_data(self):
        """Test building result with data"""
        data = [{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}]
        result = PaginationResult.build(data, total_count=10, page=1, limit=2)

        assert result["pagination"]["total_records"] == 10
        assert result["pagination"]["total_pages"] == 5  # ceil(10/2)
        assert result["pagination"]["current_page"] == 1
        assert result["data"] == data

    def test_build_with_empty_data(self):
        """Test building result with empty data"""
        result = PaginationResult.build([], total_count=0, page=1, limit=10)

        assert result["pagination"]["total_records"] == 0
        assert result["pagination"]["total_pages"] == 0
        assert result["pagination"]["current_page"] == 1
        assert result["data"] == []

    def test_build_calculates_total_pages_correctly(self):
        """Test that total_pages is calculated correctly"""
        result = PaginationResult.build([], total_count=15, page=1, limit=4)
        assert result["pagination"]["total_pages"] == 4  # ceil(15/4)

        result = PaginationResult.build([], total_count=16, page=1, limit=4)
        assert result["pagination"]["total_pages"] == 4  # ceil(16/4)

        result = PaginationResult.build([], total_count=17, page=1, limit=4)
        assert result["pagination"]["total_pages"] == 5  # ceil(17/4)

    def test_build_with_none_limit(self):
        """Test building result with None limit"""
        data = [{"id": 1}]
        result = PaginationResult.build(data, total_count=100, page=1, limit=None)

        assert result["pagination"]["total_records"] == 100
        assert result["pagination"]["total_pages"] == 1  # No pagination
        assert result["pagination"]["current_page"] == 1
        assert result["data"] == data

    def test_build_last_page_partial(self):
        """Test building result for last page with partial data"""
        data = [{"id": 8}, {"id": 9}, {"id": 10}]
        result = PaginationResult.build(data, total_count=10, page=4, limit=3)

        assert result["pagination"]["total_records"] == 10
        assert result["pagination"]["total_pages"] == 4  # ceil(10/3)
        assert result["pagination"]["current_page"] == 4
        assert len(result["data"]) == 3

    def test_build_large_dataset(self):
        """Test building result for large dataset"""
        result = PaginationResult.build([], total_count=1000, page=5, limit=50)

        assert result["pagination"]["total_records"] == 1000
        assert result["pagination"]["total_pages"] == 20  # 1000/50
        assert result["pagination"]["current_page"] == 5

    def test_build_single_page(self):
        """Test building result when all data fits in one page"""
        data = [{"id": i} for i in range(5)]
        result = PaginationResult.build(data, total_count=5, page=1, limit=10)

        assert result["pagination"]["total_records"] == 5
        assert result["pagination"]["total_pages"] == 1
        assert result["pagination"]["current_page"] == 1
        assert len(result["data"]) == 5


class TestPaginationTypedDicts:
    """Test TypedDict definitions"""

    def test_pagination_params_structure(self):
        """Test PaginationParams TypedDict structure"""
        params: PaginationParams = {
            "page": 1,
            "limit": 10,
            "skip": 0,
            "order_by": "id__DESC",
        }
        assert params["page"] == 1
        assert params["limit"] == 10
        assert params["skip"] == 0
        assert params["order_by"] == "id__DESC"

    def test_pagination_params_with_none(self):
        """Test PaginationParams with None values"""
        params: PaginationParams = {
            "page": 1,
            "limit": None,
            "skip": 0,
            "order_by": None,
        }
        assert params["limit"] is None
        assert params["order_by"] is None
